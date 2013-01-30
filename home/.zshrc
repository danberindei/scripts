# Lines configured by zsh-newuser-install
HISTFILE=~/.histfile
HISTSIZE=10000
SAVEHIST=10000
setopt EXTENDED_HISTORY
setopt SHARE_HISTORY
setopt HIST_IGNORE_ALL_DUPS

bindkey -e
# End of lines configured by zsh-newuser-install

# home/end keys
if [[ "$TERM" != emacs ]]; then
[[ -z "$terminfo[kdch1]" ]] || bindkey -M emacs "$terminfo[kdch1]" delete-char
[[ -z "$terminfo[khome]" ]] || bindkey -M emacs "$terminfo[khome]" beginning-of-line
[[ -z "$terminfo[kend]" ]] || bindkey -M emacs "$terminfo[kend]" end-of-line
[[ -z "$terminfo[kich1]" ]] || bindkey -M emacs "$terminfo[kich1]" overwrite-mode
[[ -z "$terminfo[kdch1]" ]] || bindkey -M vicmd "$terminfo[kdch1]" vi-delete-char
[[ -z "$terminfo[khome]" ]] || bindkey -M vicmd "$terminfo[khome]" vi-beginning-of-line
[[ -z "$terminfo[kend]" ]] || bindkey -M vicmd "$terminfo[kend]" vi-end-of-line
[[ -z "$terminfo[kich1]" ]] || bindkey -M vicmd "$terminfo[kich1]" overwrite-mode

[[ -z "$terminfo[cuu1]" ]] || bindkey -M viins "$terminfo[cuu1]" vi-up-line-or-history
[[ -z "$terminfo[cuf1]" ]] || bindkey -M viins "$terminfo[cuf1]" vi-forward-char
[[ -z "$terminfo[kcuu1]" ]] || bindkey -M viins "$terminfo[kcuu1]" vi-up-line-or-history
[[ -z "$terminfo[kcud1]" ]] || bindkey -M viins "$terminfo[kcud1]" vi-down-line-or-history
[[ -z "$terminfo[kcuf1]" ]] || bindkey -M viins "$terminfo[kcuf1]" vi-forward-char
[[ -z "$terminfo[kcub1]" ]] || bindkey -M viins "$terminfo[kcub1]" vi-backward-char

# ncurses fogyatekos
[[ "$terminfo[kcuu1]" == "^[O"* ]] && bindkey -M viins "${terminfo[kcuu1]/O/[}" vi-up-line-or-history
[[ "$terminfo[kcud1]" == "^[O"* ]] && bindkey -M viins "${terminfo[kcud1]/O/[}" vi-down-line-or-history
[[ "$terminfo[kcuf1]" == "^[O"* ]] && bindkey -M viins "${terminfo[kcuf1]/O/[}" vi-forward-char
[[ "$terminfo[kcub1]" == "^[O"* ]] && bindkey -M viins "${terminfo[kcub1]/O/[}" vi-backward-char
[[ "$terminfo[khome]" == "^[O"* ]] && bindkey -M viins "${terminfo[khome]/O/[}" beginning-of-line
[[ "$terminfo[kend]" == "^[O"* ]] && bindkey -M viins "${terminfo[kend]/O/[}" end-of-line
[[ "$terminfo[khome]" == "^[O"* ]] && bindkey -M emacs "${terminfo[khome]/O/[}" beginning-of-line
[[ "$terminfo[kend]" == "^[O"* ]] && bindkey -M emacs "${terminfo[kend]/O/[}" end-of-line
fi

# ctrl+arrows
bindkey ";5D" backward-word
bindkey ";5C" forward-word

# The following lines were added by compinstall
zstyle :compinstall filename '/home/dan/.zshrc'

autoload -Uz compinit
compinit
# End of lines added by compinstall

# autocompletion display options
zstyle ':completion:*:descriptions' format '%U%B%d%b%u'
zstyle ':completion:*:warnings' format '%BSorry, no matches for: %d%b'

# Allow color names in prompt
autoload -U colors
colors

# Allow functions in the prompt
setopt PROMPT_SUBST

# show the branch in the prompt and in the title
autoload -Uz vcs_info
vcs_info

zstyle ':vcs_info:*' actionformats \
    '(%b)|%a '
zstyle ':vcs_info:*' formats       \
    '(%b) '
zstyle ':vcs_info:(sv[nk]|bzr):*' branchformat '%b%:%r'

zstyle ':vcs_info:*' enable git cvs svn

case $TERM in
    xterm*)
        precmd () {
            notify_long_command_result $?
            vcs_info
            print -Pn "\e]0;%~ ${vcs_info_msg_0_}: %n@%m\a"
        }
        ;;
esac


preexec () {
    echo -e "\033[1A`date +%H:%M:%S` "
    export LAST_CMD_START_TIME=`date +%s`
    print -Pn "\e]0;* %~ ${vcs_info_msg_0_}: %n@%m\a"
}

function vcs_info_prompt() {
    # assume vcs_info has already been run by precmd()
    if [ -n "$vcs_info_msg_0_" ]; then
        echo "%{$fg[yellow]%}${vcs_info_msg_0_}%{$reset_color%}$del"
    fi
}

function notify_long_command_result() {
  LAST_CMD=`fc -ln -1`
  LAST_CMD_END_TIME=`date +%s`
  if [ -n "$LAST_CMD_START_TIME" ] ; then
    LAST_CMD_DURATION=$(($LAST_CMD_END_TIME - $LAST_CMD_START_TIME)) 
    LAST_CMD_START_TIME=
  else
    LAST_CMD_DURATION=0
  fi
  if [ $LAST_CMD_DURATION -ge 10 ] ; then
    if [ $1 -ne 0 ] ; then 
      shift
      #notify-send -t 10000 "FAILED $LAST_CMD" "$LAST_CMD"
      echo Failed after ${LAST_CMD_DURATION}s: $LAST_CMD
    else
      shift
      #notify-send -t 10000 "SUCCEEDED $LAST_CMD" "$LAST_CMD"
      echo Finished after ${LAST_CMD_DURATION}s: $LAST_CMD
    fi
 fi
}


RPROMPT='$(vcs_info_prompt)'


# enter directory name to cd
setopt autocd

# directory shortcuts
ispn=~/Work/infinispan
jgroups=~/Work/JGroups
jdg=~/Work/jdg
radargun=~/Work/radargun
logs=~/Work/logs
: ~ispn ~jgroups ~jdg ~radargun ~logs
#bo_saas=~/Work/blueoptima/blueoptima_saas
#bo_jboss=~/Work/blueoptima/jboss-5.1.0.GA
#: ~bo_jboss ~bo_saas


alias l=less
alias ll='ls -lh'
alias jps='jps -l'
alias mvn='mvn -P-extra'

alias gco='git checkout'
alias gbr='git branch'
alias gst='git status'
alias gss='git stash save'
alias gsp='git stash pop'
alias gsl='git stash list'
alias gre='git rebase'
alias gri='git rebase -i'
alias grc='git rebase --continue'
alias grs='git rebase --skip'
alias gdiff='git diff'
alias gcommit='git commit'
alias gfetch='git fetch'
alias gpull='git pull'
alias gpush='git push'

#. ~/Work/build_functions.sh

