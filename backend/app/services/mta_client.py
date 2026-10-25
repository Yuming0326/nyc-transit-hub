"""Integration boundary for the teammate implementing live MTA feeds.

Next: configure official feed URLs, request protobuf with a timeout, decode
FeedMessage, map stop IDs, normalize results, handle stale feeds and failures.
Do not point TRANSIT_MODE at live until this adapter is implemented and tested.
"""
def fetch_feed(feed_url):
    raise NotImplementedError('Live MTA feed integration is a follow-up task.')
