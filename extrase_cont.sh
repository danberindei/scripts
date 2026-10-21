#!/bin/bash

set -euo pipefail
shopt -s nullglob

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)

for f in ./*.pdf; do
  if ! TEXT=$(pdftotext "$f" -); then
    printf 'Cannot extract PDF text: %s\n' "$f" >&2
    continue
  fi
  case "$TEXT" in
    *"BANCA TRANSILVANIA"*)
      NEW_NAME=$(printf '%s\n' "$TEXT" | perl "$SCRIPT_DIR/bt_statement_name.pl")
      if [[ ! $NEW_NAME =~ ^BT_(RON|EUR)_[A-Z0-9]+_[0-9]{4}-[0-9]{2}$ ]]; then
        printf 'Cannot determine BT statement name: %s\n' "$f" >&2
        exit 1
      fi
      ;;
    *"Salt Bank"*)
      NEW_NAME=$(printf '%s\n' "$TEXT" | perl -0777 -ne '
        my %months;
        @months{qw(Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec)} = (1..12);
        my ($month, $year) = /Perioada:\s*\d{2}\.\w{3}\.\d{4}\s*-\s*\d{2}\.(\w{3})\.(\d{4})/;
        my ($iban) = /IBAN:\s*(RO\d{2}(?:\h*[A-Z0-9]{4}){5})/;
        my ($currency) = /Moneda:.*?^\h*(Lei|[A-Z]{3})\h*$/ms;
        die "Cannot determine Salt statement name\n"
          unless defined($month) && $months{$month} && defined($iban) && defined($currency);
        $iban =~ s/\h//g;
        $currency = "RON" if $currency eq "Lei";
        printf "SALT_%s_%s_%s-%02d\n", $currency, $iban, $year, $months{$month};
      ')
      ;;
    *"Wise Europe SA"*|*"Wise Assets Europe AS"*)
      NEW_NAME=$(perl -e '
        my $name = shift;
        if ($name =~ /^statement_(\d+)_([A-Z]{3})_\d{4}-\d{2}-\d{2}_(\d{4}-\d{2})-\d{2}\.pdf$/) {
          print "WISE_${2}_${1}_${3}\n";
        } elsif ($name =~ /^holdings-statement-(P\d+)-(\d{4})(\d{2})(\d{2})[+-]\d{4}\.pdf$/) {
          print "WISE_holdings_${1}_${2}-${3}-${4}\n";
        } elsif ($name =~ /^(WISE_(?:[A-Z]{3}_\d+_\d{4}-\d{2}|holdings_P\d+_\d{4}-\d{2}-\d{2}))\.pdf$/) {
          print "$1\n";
        } else {
          die "Cannot determine Wise statement name: $name\n";
        }
      ' "${f##*/}")
      ;;
    *"Extras de Cont"*)
      NEW_NAME=$(printf '%s\n' "$TEXT" | perl "$SCRIPT_DIR/alpha_statement_name.pl")
      ;;
    *)
      printf 'Unrecognized statement: %s\n' "$f" >&2
      continue
      ;;
  esac
  if [ ${#NEW_NAME} -gt 10 ] ; then
    if [ ! -e "${NEW_NAME}.pdf" ] ; then
      printf 'mv %s %s\n' "$f" "${NEW_NAME}.pdf"
      mv -- "$f" "${NEW_NAME}.pdf"
    fi
  fi
done
