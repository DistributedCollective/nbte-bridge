from . import key_value_store  # noqa


def load_models() -> None:
    # Ensure that all models are loaded
    # TODO: a scanner would be better
    import bridge.bridges.tap_rsk.models  # noqa
    import bridge.bridges.runes.models  # noqa
