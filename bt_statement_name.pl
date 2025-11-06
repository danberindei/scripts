#!/usr/bin/perl
#!/usr/bin/perl -d:Trace

BEGIN { $collect_name = 0; $collect_date = 0; $collect_number = 0; }
while (<>) {
  next if /^$/;
  if (/(^RON|^EUR)/) { $valuta = $1; };
  if (/din \d{2}\/(\d{2})\/(\d{4})/) { $luna = $1 ; $an = $2; };
  if (/Cod IBAN: (.*)/) { $iban = $1; };
}
END { print "BT_${valuta}_${iban}_${an}-${luna}\n"; }

