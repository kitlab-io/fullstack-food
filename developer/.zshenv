export PATH="$HOME/.cargo/env:$PATH"

# uv
export PATH="/Users/michael.garrido/.local/bin:$PATH"
export PATH="/Users/michael.garrido/homebrew/Cellar/pyenv/2.5.3/libexec/:$PATH"
export PYENV_ROOT="/Users/michael.garrido/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
# [[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - zsh)"
