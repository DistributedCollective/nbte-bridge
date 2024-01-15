import sys
import time
import logging
from Pyro5 import config, core, serializers, protocol, errors, socketutil
from Pyro5.client import _RemoteMethod, _StreamResultIterator, SerializedBlob
from Pyro5.callcontext import current_context
from bridge.auth import challenge

try:
    from greenlet import getcurrent as get_ident
except ImportError:
    from threading import get_ident


log = logging.getLogger("Pyro5.client")


class BoundPyroProxy(object):
    """
    Pyro BoundPyroProxy for a remote object. Intercepts method calls and dispatches them to the remote object.

    .. automethod:: _pyroBind
    .. automethod:: _pyroRelease
    .. automethod:: _pyroReconnect
    .. automethod:: _pyroValidateHandshake
    .. autoattribute:: _pyroTimeout
    .. attribute:: _pyroMaxRetries

        Number of retries to perform on communication calls by this BoundPyroProxy, allows you to override the default setting.

    .. attribute:: _pyroSerializer

        Name of the serializer to use by this BoundPyroProxy, allows you to override the default setting.

    .. attribute:: _pyroHandshake

        The data object that should be sent in the initial connection handshake message. Can be any serializable object.

    .. attribute:: _pyroLocalSocket

        The socket that is used locally to connect to the remote daemon.
        The format depends on the address family used for the connection, but usually
        for IPV4 connections it is the familiar (hostname, port) tuple.
        Consult the Python documentation on `socket families <https://docs.python.org/3/library/socket.html#socket-families>`_
        for more details
    """

    __pyroAttributes = frozenset(
        [
            "__getnewargs__",
            "__getnewargs_ex__",
            "__getinitargs__",
            "_pyroConnection",
            "_pyroUri",
            "_pyroOneway",
            "_pyroMethods",
            "_pyroAttrs",
            "_pyroTimeout",
            "_pyroSeq",
            "_pyroLocalSocket",
            "_pyroRawWireResponse",
            "_pyroHandshake",
            "_pyroMaxRetries",
            "_pyroSerializer",
            "_BoundPyroProxy__pyroTimeout",
            "_BoundPyroProxy__pyroOwnerThread",
            "_pyroPrivKey",  # added
        ]
    )

    def __init__(self, uri, connected_socket=None, privkey=None):
        if connected_socket:
            uri = core.URI("PYRO:" + uri + "@<<connected-socket>>:0")
        if isinstance(uri, str):
            uri = core.URI(uri)
        elif not isinstance(uri, core.URI):
            raise TypeError("expected Pyro URI")
        self._pyroPrivKey = privkey  # Added private key
        self._pyroUri = uri
        self._pyroConnection = None
        self._pyroSerializer = None  # can be set to the name of a serializer to override the global one per-BoundPyroProxy
        self._pyroMethods = set()  # all methods of the remote object, gotten from meta-data
        self._pyroAttrs = set()  # attributes of the remote object, gotten from meta-data
        self._pyroOneway = set()  # oneway-methods of the remote object, gotten from meta-data
        self._pyroSeq = 0  # message sequence number
        self._pyroRawWireResponse = False  # internal switch to enable wire level responses
        self._pyroHandshake = "hello"  # the data object that should be sent in the initial connection handshake message
        self._pyroMaxRetries = config.MAX_RETRIES
        self.__pyroTimeout = config.COMMTIMEOUT
        self.__pyroOwnerThread = get_ident()  # the thread that owns this BoundPyroProxy
        if config.SERIALIZER not in serializers.serializers:
            raise ValueError("unknown serializer configured")
        # note: we're not clearing the client annotations dict here.
        #       that is because otherwise it will be wiped if a new BoundPyroProxy is needed to connect PYRONAME uris.
        #       clearing the response annotations is okay.
        current_context.response_annotations = {}
        if connected_socket:
            self.__pyroCreateConnection(False, connected_socket)

    def __del__(self):
        if hasattr(self, "_pyroConnection"):
            try:
                self._pyroRelease()
            except Exception:
                pass

    def __getattr__(self, name):
        if name in BoundPyroProxy.__pyroAttributes:
            # allows it to be safely pickled
            raise AttributeError(name)
        # get metadata if it's not there yet
        if not self._pyroMethods and not self._pyroAttrs:
            self._pyroGetMetadata()
        if name in self._pyroAttrs:
            return self._pyroInvoke("__getattr__", (name,), None)
        if name not in self._pyroMethods:
            # client side check if the requested attr actually exists
            raise AttributeError(
                "remote object '%s' has no exposed attribute or method '%s'" % (self._pyroUri, name)
            )
        return _RemoteMethod(self._pyroInvoke, name, self._pyroMaxRetries)

    def __setattr__(self, name, value):
        if name in BoundPyroProxy.__pyroAttributes:
            return super(BoundPyroProxy, self).__setattr__(
                name, value
            )  # one of the special pyro attributes
        # get metadata if it's not there yet
        if not self._pyroMethods and not self._pyroAttrs:
            self._pyroGetMetadata()
        if name in self._pyroAttrs:
            return self._pyroInvoke("__setattr__", (name, value), None)  # remote attribute
        # client side validation if the requested attr actually exists
        raise AttributeError(
            "remote object '%s' has no exposed attribute '%s'" % (self._pyroUri, name)
        )

    def __repr__(self):
        if self._pyroConnection:
            connected = "connected " + self._pyroConnection.family()
        else:
            connected = "not connected"
        return "<%s.%s at 0x%x; %s; for %s; owner %s>" % (
            self.__class__.__module__,
            self.__class__.__name__,
            id(self),
            connected,
            self._pyroUri,
            self.__pyroOwnerThread,
        )

    def __getstate__(self):
        # make sure a tuple of just primitive types are used to allow for proper serialization
        return (
            str(self._pyroUri),
            tuple(self._pyroOneway),
            tuple(self._pyroMethods),
            tuple(self._pyroAttrs),
            self._pyroHandshake,
            self._pyroSerializer,
        )

    def __setstate__(self, state):
        self._pyroUri = core.URI(state[0])
        self._pyroOneway = set(state[1])
        self._pyroMethods = set(state[2])
        self._pyroAttrs = set(state[3])
        self._pyroHandshake = state[4]
        self._pyroSerializer = state[5]
        self.__pyroTimeout = config.COMMTIMEOUT
        self._pyroMaxRetries = config.MAX_RETRIES
        self._pyroConnection = None
        self._pyroLocalSocket = None
        self._pyroSeq = 0
        self._pyroRawWireResponse = False
        self.__pyroOwnerThread = get_ident()

    def __copy__(self):
        p = object.__new__(type(self))
        p.__setstate__(self.__getstate__())
        p._pyroTimeout = self._pyroTimeout
        p._pyroRawWireResponse = self._pyroRawWireResponse
        p._pyroMaxRetries = self._pyroMaxRetries
        return p

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._pyroRelease()

    def __eq__(self, other):
        if other is self:
            return True
        return isinstance(other, BoundPyroProxy) and other._pyroUri == self._pyroUri

    def __ne__(self, other):
        if other and isinstance(other, BoundPyroProxy):
            return other._pyroUri != self._pyroUri
        return True

    def __hash__(self):
        return hash(self._pyroUri)

    def __dir__(self):
        result = dir(self.__class__) + list(self.__dict__.keys())
        return sorted(set(result) | self._pyroMethods | self._pyroAttrs)

    # When special methods are invoked via special syntax (e.g. obj[index] calls
    # obj.__getitem__(index)), the special methods are not looked up via __getattr__
    # for efficiency reasons; instead, their presence is checked directly.
    # Thus we need to define them here to force (remote) lookup through __getitem__.
    def __bool__(self):
        return True

    def __len__(self):
        return self.__getattr__("__len__")()

    def __getitem__(self, index):
        return self.__getattr__("__getitem__")(index)

    def __setitem__(self, index, val):
        return self.__getattr__("__setitem__")(index, val)

    def __delitem__(self, index):
        return self.__getattr__("__delitem__")(index)

    def __iter__(self):
        try:
            # use remote iterator if it exists
            yield from self.__getattr__("__iter__")()
        except AttributeError:
            # fallback to indexed based iteration
            try:
                yield from (self[index] for index in range(sys.maxsize))
            except (StopIteration, IndexError):
                return

    def _pyroRelease(self):
        """release the connection to the pyro daemon"""
        self.__check_owner()
        if self._pyroConnection is not None:
            self._pyroConnection.close()
            self._pyroConnection = None
            self._pyroLocalSocket = None

    def _pyroBind(self):
        """
        Bind this BoundPyroProxy to the exact object from the uri. That means that the BoundPyroProxy's uri
        will be updated with a direct PYRO uri, if it isn't one yet.
        If the BoundPyroProxy is already bound, it will not bind again.
        """
        return self.__pyroCreateConnection(True)

    def __pyroGetTimeout(self):
        return self.__pyroTimeout

    def __pyroSetTimeout(self, timeout):
        self.__pyroTimeout = timeout
        if self._pyroConnection is not None:
            self._pyroConnection.timeout = timeout

    _pyroTimeout = property(
        __pyroGetTimeout,
        __pyroSetTimeout,
        doc="""
        The timeout in seconds for calls on this BoundPyroProxy. Defaults to ``None``.
        If the timeout expires before the remote method call returns,
        Pyro will raise a :exc:`Pyro5.errors.TimeoutError`""",
    )

    def _pyroInvoke(self, methodname, vargs, kwargs, flags=0, objectId=None):
        """perform the remote method call communication"""
        self.__check_owner()
        current_context.response_annotations = {}
        if self._pyroConnection is None:
            self.__pyroCreateConnection()
        serializer = serializers.serializers[self._pyroSerializer or config.SERIALIZER]
        objectId = objectId or self._pyroConnection.objectId
        annotations = current_context.annotations
        if vargs and isinstance(vargs[0], SerializedBlob):
            # special serialization of a 'blob' that stays serialized
            data, flags = self.__serializeBlobArgs(
                vargs, kwargs, annotations, flags, objectId, methodname, serializer
            )
        else:
            # normal serialization of the remote call
            data = serializer.dumpsCall(objectId, methodname, vargs, kwargs)
        if methodname in self._pyroOneway:
            flags |= protocol.FLAGS_ONEWAY
        self._pyroSeq = (self._pyroSeq + 1) & 0xFFFF
        msg = protocol.SendingMessage(
            protocol.MSG_INVOKE,
            flags,
            self._pyroSeq,
            serializer.serializer_id,
            data,
            annotations=annotations,
        )
        if config.LOGWIRE:
            protocol.log_wiredata(log, "BoundPyroProxy wiredata sending", msg)
        try:
            self._pyroConnection.send(msg.data)
            del msg  # invite GC to collect the object, don't wait for out-of-scope
            if flags & protocol.FLAGS_ONEWAY:
                return None  # oneway call, no response data
            else:
                msg = protocol.recv_stub(self._pyroConnection, [protocol.MSG_RESULT])
                if config.LOGWIRE:
                    protocol.log_wiredata(log, "BoundPyroProxy wiredata received", msg)
                self.__pyroCheckSequence(msg.seq)
                if msg.serializer_id != serializer.serializer_id:
                    error = "invalid serializer in response: %d" % msg.serializer_id
                    log.error(error)
                    raise errors.SerializeError(error)
                if msg.annotations:
                    current_context.response_annotations = msg.annotations
                if self._pyroRawWireResponse:
                    return msg
                data = serializer.loads(msg.data)
                if msg.flags & protocol.FLAGS_ITEMSTREAMRESULT:
                    streamId = bytes(msg.annotations.get("STRM", b"")).decode()
                    if not streamId:
                        raise errors.ProtocolError(
                            "result of call is an iterator, but the server is not configured to allow streaming"
                        )
                    return _StreamResultIterator(streamId, self)
                if msg.flags & protocol.FLAGS_EXCEPTION:
                    raise data  # if you see this in your traceback, you should probably inspect the remote traceback as well
                else:
                    return data
        except (errors.CommunicationError, KeyboardInterrupt):
            # Communication error during read. To avoid corrupt transfers, we close the connection.
            # Otherwise we might receive the previous reply as a result of a new method call!
            # Special case for keyboardinterrupt: people pressing ^C to abort the client
            # may be catching the keyboardinterrupt in their code. We should probably be on the
            # safe side and release the BoundPyroProxy connection in this case too, because they might
            # be reusing the BoundPyroProxy object after catching the exception...
            self._pyroRelease()
            raise

    def __pyroCheckSequence(self, seq):
        if seq != self._pyroSeq:
            err = "invoke: reply sequence out of sync, got %d expected %d" % (seq, self._pyroSeq)
            log.error(err)
            raise errors.ProtocolError(err)

    def __pyroCreateConnection(self, replaceUri=False, connected_socket=None):
        """
        Connects this BoundPyroProxy to the remote Pyro daemon. Does connection handshake.
        Returns true if a new connection was made, false if an existing one was already present.
        """

        def connect_and_handshake(conn):  # Added private key
            try:
                if self._pyroConnection is not None:
                    return False  # already connected
                if config.SSL:
                    sslContext = socketutil.get_ssl_context(
                        clientcert=config.SSL_CLIENTCERT,
                        clientkey=config.SSL_CLIENTKEY,
                        keypassword=config.SSL_CLIENTKEYPASSWD,
                        cacerts=config.SSL_CACERTS,
                    )
                else:
                    sslContext = None
                sock = socketutil.create_socket(
                    connect=connect_location,
                    reuseaddr=config.SOCK_REUSE,
                    timeout=self.__pyroTimeout,
                    nodelay=config.SOCK_NODELAY,
                    sslContext=sslContext,
                )
                conn = socketutil.SocketConnection(sock, uri.object)
                # Do handshake.
                serializer = serializers.serializers[self._pyroSerializer or config.SERIALIZER]

                if config.SSL:  # Added part
                    channel_binding = conn.sock.get_channel_binding(cb_type="tls-unique")

                    data = {
                        "handshake": challenge.initial_challenge(
                            channel_binding, self._pyroPrivKey
                        ),
                        "object": uri.object,
                    }
                else:
                    data = {"handshake": self._pyroHandshake, "object": uri.object}

                data = serializer.dumps(data)

                msg = protocol.SendingMessage(
                    protocol.MSG_CONNECT,
                    0,
                    self._pyroSeq,
                    serializer.serializer_id,
                    data,
                    annotations=current_context.annotations,
                )
                if config.LOGWIRE:
                    protocol.log_wiredata(log, "BoundPyroProxy connect sending", msg)

                print("SENDING:DD")
                conn.send(msg.data)
                msg = protocol.recv_stub(conn, [protocol.MSG_CONNECTOK, protocol.MSG_CONNECTFAIL])
                if config.LOGWIRE:
                    protocol.log_wiredata(log, "BoundPyroProxy connect response received", msg)
            except Exception as x:
                if conn:
                    conn.close()
                err = "cannot connect to %s: %s" % (connect_location, x)
                log.error(err)
                if isinstance(x, errors.CommunicationError):
                    raise
                else:
                    raise errors.CommunicationError(err) from x
            else:
                handshake_response = "?"
                if msg.data:
                    serializer = serializers.serializers_by_id[msg.serializer_id]
                    handshake_response = serializer.loads(msg.data)
                if msg.type == protocol.MSG_CONNECTFAIL:
                    error = "connection to %s rejected: %s" % (connect_location, handshake_response)
                    conn.close()
                    log.error(error)
                    raise errors.CommunicationError(error)
                elif msg.type == protocol.MSG_CONNECTOK:
                    self.__processMetadata(handshake_response["meta"])
                    handshake_response = handshake_response["handshake"]
                    self._pyroConnection = conn
                    self._pyroLocalSocket = conn.sock.getsockname()
                    if replaceUri:
                        self._pyroUri = uri
                    self._pyroValidateHandshake(handshake_response)
                    log.debug(
                        "connected to %s - %s - %s",
                        self._pyroUri,
                        conn.family(),
                        "SSL" if sslContext else "unencrypted",
                    )
                    if msg.annotations:
                        current_context.response_annotations = msg.annotations
                else:
                    conn.close()
                    err = "cannot connect to %s: invalid msg type %d received" % (
                        connect_location,
                        msg.type,
                    )
                    log.error(err)
                    raise errors.ProtocolError(err)

        self.__check_owner()
        if self._pyroConnection is not None:
            return False  # already connected
        uri = core.resolve(self._pyroUri)
        # socket connection (normal or Unix domain socket)
        conn = None
        log.debug("connecting to %s", uri)
        connect_location = uri.sockname or (uri.host, uri.port)
        if connected_socket:
            self._pyroConnection = socketutil.SocketConnection(connected_socket, uri.object, True)
            self._pyroLocalSocket = connected_socket.getsockname()
        else:
            connect_and_handshake(conn)
        # obtain metadata if this feature is enabled, and the metadata is not known yet
        if not self._pyroMethods and not self._pyroAttrs:
            self._pyroGetMetadata(uri.object)
        return True

    def _pyroGetMetadata(self, objectId=None, known_metadata=None):
        """
        Get metadata from server (methods, attrs, oneway, ...) and remember them in some attributes of the BoundPyroProxy.
        Usually this will already be known due to the default behavior of the connect handshake, where the
        connect response also includes the metadata.
        """
        objectId = objectId or self._pyroUri.object
        log.debug("getting metadata for object %s", objectId)
        if self._pyroConnection is None and not known_metadata:
            try:
                self.__pyroCreateConnection()
            except errors.PyroError:
                log.error("problem getting metadata: cannot connect")
                raise
            if self._pyroMethods or self._pyroAttrs:
                return  # metadata has already been retrieved as part of creating the connection
        try:
            # invoke the get_metadata method on the daemon
            result = known_metadata or self._pyroInvoke(
                "get_metadata", [objectId], {}, objectId=core.DAEMON_NAME
            )
            self.__processMetadata(result)
        except errors.PyroError:
            log.exception("problem getting metadata")
            raise

    def __processMetadata(self, metadata):
        if not metadata:
            return
        self._pyroOneway = set(metadata["oneway"])
        self._pyroMethods = set(metadata["methods"])
        self._pyroAttrs = set(metadata["attrs"])
        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                "from meta: methods=%s, oneway methods=%s, attributes=%s",
                sorted(self._pyroMethods),
                sorted(self._pyroOneway),
                sorted(self._pyroAttrs),
            )
        if not self._pyroMethods and not self._pyroAttrs:
            raise errors.PyroError(
                "remote object doesn't expose any methods or attributes. Did you forget setting @expose on them?"
            )

    def _pyroReconnect(self, tries=100000000):
        """
        (Re)connect the BoundPyroProxy to the daemon containing the pyro object which the BoundPyroProxy is for.
        In contrast to the _pyroBind method, this one first releases the connection (if the BoundPyroProxy is still connected)
        and retries making a new connection until it succeeds or the given amount of tries ran out.
        """
        self._pyroRelease()
        while tries:
            try:
                self.__pyroCreateConnection()
                return
            except errors.CommunicationError:
                tries -= 1
                if tries:
                    time.sleep(2)
        msg = "failed to reconnect"
        log.error(msg)
        raise errors.ConnectionClosedError(msg)

    def _pyroInvokeBatch(self, calls, oneway=False):
        flags = protocol.FLAGS_BATCH
        if oneway:
            flags |= protocol.FLAGS_ONEWAY
        return self._pyroInvoke("<batch>", calls, None, flags)

    def _pyroValidateHandshake(self, response):
        logging.debug("Validating handshake on client, response: %s", response)

        challenge.validate_message(
            response,
            self._pyroConnection.sock.get_channel_binding(cb_type="tls-unique"),
        )

        logging.debug("Handshake validated")

    def _pyroClaimOwnership(self):
        """
        The current thread claims the ownership of this BoundPyroProxy from another thread.
        Any existing connection will remain active!
        """
        if get_ident() != self.__pyroOwnerThread:
            # if self._pyroConnection is not None:
            #     self._pyroConnection.close()
            #     self._pyroConnection = None
            self.__pyroOwnerThread = get_ident()

    def __serializeBlobArgs(
        self, vargs, kwargs, annotations, flags, objectId, methodname, serializer
    ):
        """
        Special handling of a "blob" argument that has to stay serialized until explicitly deserialized in client code.
        This makes efficient, transparent gateways or dispatchers and such possible:
        they don't have to de/reserialize the message and are independent from the serialized class definitions.
        Annotations are passed in because some blob metadata is added. They're not part of the blob itself.
        """
        if len(vargs) > 1 or kwargs:
            raise errors.SerializeError("if SerializedBlob is used, it must be the only argument")
        blob = vargs[0]
        flags |= protocol.FLAGS_KEEPSERIALIZED
        # Pass the objectId and methodname separately in an annotation because currently,
        # they are embedded inside the serialized message data. And we're not deserializing that,
        # so we have to have another means of knowing the object and method it is meant for...
        # A better solution is perhaps to split the actual remote method arguments from the
        # control data (object + methodname) but that requires a major protocol change.
        # The code below is not as nice but it works without any protocol change and doesn't
        # require a hack either - so it's actually not bad like this.
        import marshal

        annotations["BLBI"] = marshal.dumps((blob.info, objectId, methodname))
        if blob._contains_blob:
            # directly pass through the already serialized msg data from within the blob
            protocol_msg = blob._data
            return protocol_msg.data, flags
        else:
            # replaces SerializedBlob argument with the data to be serialized
            return serializer.dumpsCall(objectId, methodname, blob._data, kwargs), flags

    def __check_owner(self):
        if get_ident() != self.__pyroOwnerThread:
            raise errors.PyroError(
                "the calling thread is not the owner of this BoundPyroProxy, "
                "create a new BoundPyroProxy in this thread or transfer ownership."
            )


def get_peer_addresses():
    # TODO: get from external service
    return [
        "0x09dcD91DF9300a81a4b9C85FDd04345C3De58F48",
        "0xA40013a058E70664367c515246F2560B82552ACb",
        "0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a",
    ]


# Forked from Pyro5.client.BoundPyroProxy.__pyroCreateConnection
# and modified to allow for a socket channel binding to be passed in
# with the data in the handshake. Please do not touch any more than necessary.
# It's ugly as it is.
