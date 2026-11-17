"""DCC-MCP bridge: a Krita Python plugin that lets the DCC-MCP server drive this Krita."""
try:
    import krita
except ImportError:  # imported by tests outside Krita: only commands.py is used there
    krita = None

if krita is not None:
    from .commands import Bridge
    from .server import BridgeServer

    class DccMcpBridge(krita.Extension):
        def setup(self) -> None:
            self.server = BridgeServer(Bridge(krita))
            krita.Krita.instance().notifier().applicationClosing.connect(self.server.close)

        def createActions(self, window) -> None:
            pass

    krita.Krita.instance().addExtension(DccMcpBridge(krita.Krita.instance()))
