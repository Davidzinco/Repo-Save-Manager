"""Translate the game's completed-level counter into its displayed stage."""


def stage_from_level(level):
    if isinstance(level, bool) or not isinstance(level, int) or level < 0:
        raise ValueError('Completed levels must be a non-negative integer.')
    return level + 1


def level_from_stage(stage):
    stage = int(stage)
    if stage < 1:
        raise ValueError('Stage must be at least 1.')
    return stage - 1
