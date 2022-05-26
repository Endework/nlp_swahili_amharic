from . import (
    plots,predictions
)


def router(page):
    match page:
        case 'make_forecast':
            predictions.make_prediction(page)
        case 'view_forecast':
            plots.view_predictions(page)
        