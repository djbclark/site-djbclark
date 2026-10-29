# :g inside BarnOwl. Loaded from ~/.owl/startup.
# The shell command g starts Grok. This command stays in-process, because
# Grok driving this same window would stall on the command that launched it.
package BarnOwl::G;

use strict;
use warnings;

sub show_subs {
    my $subs = BarnOwl::zephyr_getsubs();
    BarnOwl::popless_text(defined $subs && $subs ne '' ? $subs : "(no subscriptions)\n");
    return;
}

sub cmd {
    my ( $name, @args ) = @_;
    my $text = join ' ', @args;
    $text =~ s/^\s+|\s+$//g;
    my $norm = lc $text;
    if ( $norm =~ /^(?:(?:show|list|print|get)\s+)?(?:my\s+)?(?:subs|subscriptions)\s*$/ ) {
        show_subs();
        return;
    }
    BarnOwl::error(
        "g show my subs lists live subscriptions. "
            . "Other requests: run g from the shell, outside this window."
    );
    return;
}

BarnOwl::new_command(
    'g' => \&cmd,
    {
        summary => 'Plain English inside BarnOwl. g show my subs',
        usage   => 'g show my subs',
        description =>
            "Lists the live Zephyr subscriptions in a popup.\n"
            . "The shell command g, outside BarnOwl, runs the same request through Grok.\n",
    }
);

'g ready';
