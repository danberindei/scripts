#!/usr/bin/perl
#!/usr/bin/perl -d:Trace

BEGIN { $collect_name = 0; $collect_date = 0; $collect_number = 0; }
while (<>) {
  next if /^$/;
  if (/Extras de Cont/) { $collect_name = 1; next; }
  if ($collect_name) { $name = $_; chomp($name); $collect_name = 0; }
  if (/Pana la data:/) { $collect_date = 1; next; }
  if ($collect_date && /(\d{2})\/(\d{2})\/(\d{4})/) { $date = "$3-$2-$1"; $collect_date = 0; }
  if (/Nr. Extras:/) { $collect_number = 1; next; }
  if ($collect_number) { $number = $_; chomp($number); $collect_number = 0; }

}
END { print "$name $date ($number)\n"; }

