#compdef _build_functions.py cbuild cbtest jbuild btest jtest

(( $+functions[__git_branch_names] )) || _git

function __my_mvn_modules() {
  declare -a modules
  modules=( $(find . -name 'pom.xml' -maxdepth 5 -printf '%h\n' | sed -ne 's/^.\/// p') )
  _multi_parts / modules
}

_arguments \
  '1::branches:__git_branch_names' \
  '*:modules:__my_mvn_modules'
