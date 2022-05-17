import logging
import requests
from requests.adapters import HTTPAdapter, Retry

# Super minimal implementation of Owncast API, enough to do what owncast recorder needs


class Paths:
    API_PATH = "/api"
    STREAM_PATH = "/hls/stream.m3u8"
    PING_PATH = "/ping"
    STATUS_PATH = "/status"


class OwncastServer:
    def __init__(self, url: str, retries: int = 2, logger=None):
        """Class to help access info about an Owncast server.
            Info that does not change is cached locally, otherwise requested new.

        Args:
            url (str): [description]
        """
        self.url = url
        self.retries = retries
        self.logger = logger
        if self.logger is None:
            self.logger = logging.getLogger()
        self.cache = {}
        self.session = requests.Session()
        retry = Retry(
            total=self.retries if self.retries != -1 else None, backoff_factor=1
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _request(self, path, method="GET", headers={}, data={}):
        if method not in ("GET", "PUT", "DELETE"):
            raise ValueError(f'Invalid HTTP method "{method}"')
        try:
            resp = self.session.request(
                method, self.url + Paths.API_PATH + path, headers=headers, data=data
            )
        except requests.exceptions.ConnectionError:
            raise
        return resp

    # server functions
    def ping(self):
        resp = self._request(Paths.PING_PATH)
        return resp.status_code, resp.status_code == 200

    def status(self):
        resp = self._request(Paths.STATUS_PATH)
        try:
            return resp.status_code, (resp.json())
        except requests.JSONDecodeError:
            return resp.status_code, resp.text

    # other
    def stream_url(self):
        # https://owncast.online/docs/embed/#using-the-hls-feed
        # this may change in the future
        return self.url + Paths.STREAM_PATH
