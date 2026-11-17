from dcc_mcp.contract import Ctx, OpResult


def forward(cmd: str):
    """Most operations live in the bridge; on this side they only pass params through."""
    def run(ctx: Ctx, params: dict) -> OpResult:
        return OpResult(metrics=ctx.session.call(cmd, params))
    return run
