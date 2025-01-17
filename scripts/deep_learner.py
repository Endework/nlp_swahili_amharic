# importing of libraries
from bleach import Cleaner
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import tensorflow as tf
import os,sys
print(os.getcwd())
sys.path.append(os.path.abspath(os.path.join('../scripts')))
from logger import logger
from tensorflow import keras
from tensorflow.keras import layers
from model_serializer import ModelSerializer
from clean import Clean
import mlflow
import csv
import seaborn as sns
sns.set()


class DeepLearn:
    """
    - this class is responsible for deep learning
    """

    def __init__(self,input_width, label_width, shift,epochs=5,
                train_df=None, val_df=None, test_df=None,
                label_columns=None):
        """initialize the Deep Learn class"""
        self.epochs = epochs
        # Store the raw data.
        self.train_df = train_df
        self.val_df = val_df
        self.test_df = test_df
        # Work out the label column indices.
        self.label_columns = label_columns
        if label_columns is not None:
            self.label_columns_indices = {name: i for i, name in
                                            enumerate(label_columns)}
        self.column_indices = {name: i for i, name in
                            enumerate(train_df.columns)}
        # Work out the window parameters.
        self.input_width = input_width
        self.label_width = label_width
        self.shift = shift
        self.total_window_size = input_width + shift
        self.input_slice = slice(0, input_width)
        self.input_indices = np.arange(self.total_window_size)[self.input_slice]
        self.label_start = self.total_window_size - self.label_width
        self.labels_slice = slice(self.label_start, None)
        self.label_indices = np.arange(self.total_window_size)[self.labels_slice]

    def split_window(self, features):
        """this function splits the window"""
        inputs = features[:, self.input_slice, :]
        labels = features[:, self.labels_slice, :]
        if self.label_columns is not None:
            labels = tf.stack(
                [labels[:, :, self.column_indices[name]] for name in self.label_columns],
                axis=-1)

        # Slicing doesn't preserve static shape information, so set the shapes
        # manually. This way the `tf.data.Datasets` are easier to inspect.
        inputs.set_shape([None, self.input_width, None])
        labels.set_shape([None, self.label_width, None])

        return inputs, labels

    def make_dataset(self, data):
        """
        this function is responsible
        for making the dataset
        """
        data = np.array(data, dtype=np.float32)
        ds = tf.keras.utils.timeseries_dataset_from_array(
            data=data,
            targets=None,
            sequence_length=self.total_window_size,
            sequence_stride=1,
            shuffle=True,
            batch_size=32,)

        ds = ds.map(self.split_window)

        return ds

    @property        # Work out the label column indices.
    def train(self):
        return self.make_dataset(self.train_df)

    @property
    def val(self):
        return self.make_dataset(self.val_df)

    @property
    def test(self):
        return self.make_dataset(self.test_df)

    @property
    def get_input_labels(self):
        """Get and cache an example batch of `inputs, labels` for plotting."""
        result = getattr(self, '_res', None)
        if result is None:
            # No example batch was found, so get one from the `.train` dataset
            result = next(iter(self.train))
            # And cache it for next time
            self._res = result
        return result

    def compile_and_fit(self,model, window, patience=2):
        """this function fits the data set for prediction"""
        early_stopping = tf.keras.callbacks.EarlyStopping(monitor='val_loss',
                                                            patience=patience,
                                                            mode='min')

        model.compile(loss=tf.losses.MeanSquaredError(),
                        optimizer=tf.optimizers.Adam(),
                        metrics=[tf.metrics.MeanAbsoluteError()])

        history = model.fit(window.train, epochs=self.epochs,
                            validation_data=window.val,
                            callbacks=[early_stopping])
        return history

    def model(self,model_,serialize=False):
        """model the lstm class"""
        mlflow.tensorflow.autolog()
        model = model_
        with mlflow.start_run(run_name='deep-learner'):
            mlflow.set_tag("mlflow.runName", "deep-learner")
            learn = DeepLearn(input_width=self.input_width, label_width=self.label_width, shift=self.shift,
                     train_df=self.train_df, val_df=self.val_df, test_df=self.test_df,
                     label_columns=self.label_columns)
            inputs_, _ = learn.get_input_labels
            _ = self.compile_and_fit(model, learn)
            logger.info("Successfully executed the model")
            
            """forecast the data"""
            forecast=model(inputs_).numpy().tolist()
        if serialize:
            serializer = ModelSerializer(model)
            serializer.pickle_serialize()
        return forecast

    def plot(self, model=None, plot_col=None, max_subplots=3):
        """this algorithm checks the performance of the model"""
        plot_col = self.label_columns
        inputs, labels = self.get_input_labels
        plt.figure(figsize=(12, 8))
        plot_col_index = self.column_indices[plot_col]
        max_n = min(max_subplots, len(inputs))
        for n in range(max_n):
            plt.subplot(max_n, 1, n+1)
            plt.ylabel(f'{plot_col} [normed]')
            plt.plot(self.input_indices, inputs[n, :, plot_col_index],
                    label='Inputs', marker='.', zorder=-10)

            if self.label_columns:
                label_col_index = self.label_columns_indices.get(plot_col, None)
            else:
                label_col_index = plot_col_index

            if label_col_index is None:
                continue

            plt.scatter(self.label_indices, labels[n, :, label_col_index],
                        edgecolors='k', label='Labels', c='#2ca02c', s=64)
            if model is not None:
                predictions = model(inputs)
            plt.scatter(self.label_indices, predictions[n, :, label_col_index],
                        marker='X', edgecolors='k', label='Predictions',
                        c='#ff7f0e', s=64)

            if n == 0:
                plt.legend()

        plt.xlabel('Time')


    def CTCLoss(self,y_true, y_pred):
        # Compute the training-time loss value
        batch_len = tf.cast(tf.shape(y_true)[0], dtype="int64")
        input_length = tf.cast(tf.shape(y_pred)[1], dtype="int64")
        label_length = tf.cast(tf.shape(y_true)[1], dtype="int64")

        input_length = input_length * tf.ones(shape=(batch_len, 1), dtype="int64")
        label_length = label_length * tf.ones(shape=(batch_len, 1), dtype="int64")

        loss = keras.backend.ctc_batch_cost(y_true, y_pred, input_length, label_length)
        return loss

        
    def cnn_output_length(self, input_length, kernel_list, pool_sizes, cnn_stride, mx_stride, padding='valid'):

        if padding == 'same':
            output_length = input_length
            
            return output_length

        elif padding == 'valid':
            output_length = input_length

            for i, j, k in zip(kernel_list, pool_sizes, mx_stride):
                output_length = (output_length - i)/cnn_stride + 1
                if j != 0: output_length = (output_length - j)/k + 1
            
            return tf.math.floor(output_length)


    def build_asr_model(self,input_dim, output_dim, rnn_layers=1, rnn_units=1):
        """Model similar to DeepSpeech2."""
        # Model's input
        input_spectrogram = layers.Input((None, input_dim), name="input")
        # Expand the dimension to use 2D CNN.
        x = layers.Reshape((-1, input_dim, 1), name="expand_dim")(input_spectrogram)
        # Convolution layer 1
        x = layers.Conv2D(
            filters=2,
            kernel_size=[1, 2],
            strides=[2, 2],
            padding="same",
            use_bias=False,
            name="conv_1",
        )(x)
        x = layers.BatchNormalization(name="conv_1_bn")(x)
        x = layers.ReLU(name="conv_1_relu")(x)
        # Convolution layer 2
        x = layers.Conv2D(
            filters=2,
            kernel_size=[1, 1],
            strides=[1, 2],
            padding="same",
            use_bias=False,
            name="conv_2",
        )(x)
        x = layers.BatchNormalization(name="conv_2_bn")(x)
        x = layers.ReLU(name="conv_2_relu")(x)
        # Reshape the resulted volume to feed the RNNs layers
        x = layers.Reshape((-1, x.shape[-2] * x.shape[-1]))(x)
        # RNN layers
        for i in range(1, rnn_layers + 1):
            recurrent = layers.GRU(
                units=rnn_units,
                activation="tanh",
                recurrent_activation="sigmoid",
                use_bias=True,
                return_sequences=True,
                reset_after=True,
                name=f"gru_{i}",
            )
            x = layers.Bidirectional(
                recurrent, name=f"bidirectional_{i}", merge_mode="concat"
            )(x)
            if i < rnn_layers:
                x = layers.Dropout(rate=0.5)(x)
        # Dense layer
        x = layers.Dense(units=rnn_units * 2, name="dense_1")(x)
        x = layers.ReLU(name="dense_1_relu")(x)
        x = layers.Dropout(rate=0.5)(x)
        # Classification layer
        output = layers.Dense(units=output_dim + 1, activation="softmax")(x)
        # Model
        model = keras.Model(input_spectrogram, output, name="DeepSpeech_2")
        # Optimizer
        opt = keras.optimizers.Adam(learning_rate=1e-4)
        # Compile the model and return
        model.compile(optimizer=opt, loss=self.CTCLoss)
        return model

    def cnn_rnn_model(self, input_dim, filters, kernels, pool_sizes, mx_stride, cnn_stride, output_dim=224, num_cnn = 3, num_lstm = 4 ):

        input_spectrogram = layers.Input(name='the_input', shape=(None, input_dim))
        x = layers.Reshape((-1, input_dim, 1), dtype="float32")(input_spectrogram)
        
        # Activation function used LeakyReLU, we can also use ReLU
        # Conv Layers
        for i in range(num_cnn):
            x = layers.Conv2D(filters=filters[i], kernel_size=kernels[i], strides=1, padding='valid', name='cnn_{}'.format(i))(x)
            x = layers.LeakyReLU(.1)(x)
            x = layers.MaxPooling2D( pool_size=pool_sizes[i], strides=(1,2), padding="valid")(x)
            x = layers.BatchNormalization(name='bn_cnn_{}'.format(i))(x)
            
        x = layers.Reshape((-1, x.shape[-1] * x.shape[-2] ))(x)

        # RNN Layers
        for i in range(num_lstm):
            x = layers.Bidirectional(layers.GRU(units=512, return_sequences=True, implementation=2, name='rnn_{}'.format(i)))(x)
            x = layers.LeakyReLU(.1)(x)
            x = layers.BatchNormalization(name='bn_rnn_{}'.format(i))(x)

            if i < num_lstm:
                x = layers.Dropout(rate=0.5)(x)

        # Dense Layer
        x = layers.TimeDistributed(layers.Dense(output_dim))(x)

        # Prediction Layer
        y_pred = layers.Activation('softmax', name='softmax')(x)
        y_pred = layers.LeakyReLU(name="dense_1_relu")(y_pred) 
        y_pred = layers.Dropout(rate=0.5)(y_pred)

        # Model
        model = keras.Model( inputs=input_spectrogram, outputs=y_pred, name="CONV_RNN" )

        # Optimizer
        opt = keras.optimizers.Adam(learning_rate=1e-4)
        
        # Compile the model and print its summary 
        model.compile(optimizer=opt, loss=self.CTCLoss)
        print(model.summary())

        # Calculate the output length
        model.output_length = lambda x: self.output_length(x, kernels, pool_sizes, cnn_stride, mx_stride)

        return model

    def decode_batch_predictions(self,pred,alphabet):
        input_len = np.ones(pred.shape[0]) * pred.shape[1]
        # Use greedy search. For complex tasks, you can use beam search
        results = keras.backend.ctc_decode(pred, input_length=input_len, greedy=True)[0][0]
        # Iterate over the results and get back the text
        output_text = []
        cleaner = Clean()
        vocabs = cleaner.vocab(alphabet)
        _,num_to_char = vocabs
        for result in results:
            result = tf.strings.reduce_join(num_to_char(result)).numpy().decode("utf-8")
            output_text.append(result)
        return output_text

    
if __name__=='__main__':
    train_ = pd.read_csv("data/cleaned_train.csv")
    train_.set_index('Date',inplace=True)
    """make sales to be last column"""
    train=train_.loc[:,train_.columns!='Sales']
    train['Sales']=train_['Sales']
    n = len(train)
    train_df = train[0:int(n*0.7)]
    val_df = train[int(n*0.7):int(n*0.9)]
    test_df = train[int(n*0.9):]
    num_features = train.shape[1]
    learn = DeepLearn(input_width=1, label_width=1, shift=1,epochs=5,
                     train_df=train_df, val_df=val_df, test_df=test_df,
                     label_columns=['Sales'])
    forecast = learn.model(
        model_=tf.keras.models.Sequential([
            # Shape [batch, time, features] => [batch, time, lstm_units]
            tf.keras.layers.LSTM(32, return_sequences=True),
            # Shape => [batch, time, features]
            tf.keras.layers.Dense(units=1)
        ])
    )
    
    