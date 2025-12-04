import json
import traceback
import inspect
import asyncio

from lambdas.common.utility_helpers import build_successful_handler_response, build_error_handler_response
from lambdas.common.errors import DownloadTrackError
from lambdas.common.constants import LOGGER

log = LOGGER.get_logger(__file__)

HANDLER = 'download-tracks'


def handler(event, context):
    try:

        response = None

        return build_successful_handler_response(response)

    except Exception as err:
        message = err.args[0]
        function = f'handler.{__name__}'
        if len(err.args) > 1:
            function = err.args[1]
        log.error(traceback.print_exc())
        error = DownloadTrackError(message, HANDLER, function) if 'Invalid User Input' not in message else DownloadTrackError(message, HANDLER, function, 400)
        return build_error_handler_response(str(error))
