# :g inside BarnOwl. Loaded from ~/.owl/startup.
# The shell commands gr (Grok) and go (goose) start a model. This command stays
# in-process, because a model driving this same window would stall on the
# command that launched it.
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
            . "The shell commands gr and go, outside BarnOwl, run the same request\n"
            . "through Grok and goose.\n",
    }
);

'g ready';
