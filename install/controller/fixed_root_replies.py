"""Finite fixed-view root replies; existing grants and issue authorization."""
from s06_root_reply import RootStdinReply

class FixedRootReplies:
    def __init__(self, replies):
        self.replies=dict(replies)
        if not self.replies or any(not isinstance(reply,RootStdinReply)for reply in self.replies.values()):
            raise TypeError('fixed existing protected reply instances required')
        bindings=[reply.binding for reply in self.replies.values()]
        if any(binding==prior for i,binding in enumerate(bindings)for prior in bindings[:i]):
            raise ValueError('each full project/root reply binding must be distinct')

    def publish(self,envelope):
        if not isinstance(envelope,dict)or set(envelope)!={'schema','binding','request'}or envelope['schema']!='otto.run-local.root-stdin-reply.v1':
            raise PermissionError('exact protected root envelope required')
        matches=[reply for reply in self.replies.values()if reply.binding==envelope['binding']]
        if len(matches)!=1:raise PermissionError('full current fixed recipient binding unavailable')
        return matches[0].publish(envelope)

    def authorize_route(self,request):
        # Each port checks an independently issued exact stdin grant AND actual
        # current root/issue/delivery binding; JSON fields never select a view.
        accepted=[]
        for key,reply in self.replies.items():
            try:actor=reply.authorize(request)
            except PermissionError:continue
            accepted.append((key,actor))
        if len(accepted)!=1:raise PermissionError('one exact current protected issue view required')
        return accepted[0][0]

    def serve_stdin(self,stream,emit):
        import json
        from s06_root_reply import MAX_BYTES
        while True:
            line=stream.readline(MAX_BYTES+2)
            if not line:return
            try:
                if len(line.encode())>MAX_BYTES or not line.endswith('\n'):raise ValueError('one bounded complete JSON line required')
                emit({'root_reply_ingress':self.publish(json.loads(line))})
            except Exception as error:emit({'root_reply_ingress':{'outcome':'rejected','provider_called':False,'canonical_response_recorded':False,'error':str(error)}})
