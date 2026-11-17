-- Enable only AFTER the validation procedure in docs/LIVE_SETUP.md passes.
-- These values document an operator audit; they do not read CONTROL's private settings.
return {
    audited = false,
    build = "101.103.48987.0",
    interval = 0.5,
    horizon = 120,
    map_size = 32,
    pipe = "AoE2RL"
}
