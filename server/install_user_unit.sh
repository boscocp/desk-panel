#!/bin/sh
# Install the desk-panel server as a systemd **user** unit bound to the graphical
# session (T3.9). The Linux sibling of install_task.ps1, and it makes the same
# promise: the server is launched by, and dies with, the graphical session of a
# human user, so "it answers" means "somebody is logged in at that screen".
#
#   sh server/install_user_unit.sh                 install and start
#   sh server/install_user_unit.sh --config PATH   use a config other than the found one
#   sh server/install_user_unit.sh --no-start      install and enable, start at next login
#   sh server/install_user_unit.sh --uninstall     stop, disable, remove the unit
#
# POSIX sh, no bashisms: this runs on whatever /bin/sh the distro ships.
#
# What this script refuses to do is the interesting half. It will not install
# for root, it will not install beside a system-scoped copy of the same service,
# and it will not install where graphical-session.target never activates -- each
# of those produces a server that answers with nobody at the desk, which is the
# failure docs/adr/0010-login-signal-is-session-scoped.md exists to forbid and
# which looks exactly like a working installation from every angle but one.

set -eu

UNIT_NAME=desk-panel.service
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
# `CDPATH= cd` is a one-command assignment, not a typo: it clears CDPATH so
# `cd` cannot land somewhere else and print the path it chose. Emptying CDPATH
# for the whole script would change the caller's environment instead.
# shellcheck disable=SC1007
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname -- "$SCRIPT_DIR")
TEMPLATE="$SCRIPT_DIR/desk-panel.service.in"
SERVER_PY="$SCRIPT_DIR/server.py"

CONFIG=
PYTHON=${DESK_PANEL_PYTHON:-}
START=yes
UNINSTALL=no

step() { printf '==> %s\n' "$1"; }
note() { printf '    %s\n' "$1"; }
die() { printf 'install_user_unit.sh: %s\n' "$1" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --config) [ $# -ge 2 ] || die "--config needs a path"; CONFIG=$2; shift 2 ;;
        --config=*) CONFIG=${1#--config=}; shift ;;
        --python) [ $# -ge 2 ] || die "--python needs a path"; PYTHON=$2; shift 2 ;;
        --python=*) PYTHON=${1#--python=}; shift ;;
        --no-start) START=no; shift ;;
        --uninstall) UNINSTALL=yes; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) die "unknown option $1" ;;
    esac
done

command -v systemctl >/dev/null 2>&1 || die "no systemctl on PATH; this machine does not use systemd"

# Root has no graphical session of its own to be scoped to, and `sudo sh
# install_user_unit.sh` would install this into root's user manager -- where it
# would be enabled, invisible to the owner's `systemctl --user`, and started by
# nothing. It is also the shape of the mistake that turns this into a service.
[ "$(id -u)" -ne 0 ] || die "do not run this as root or under sudo: it installs a *user* unit into your own session"

if [ "$UNINSTALL" = yes ]; then
    step "Removing $UNIT_NAME"
    systemctl --user disable --now "$UNIT_NAME" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$UNIT_NAME"
    systemctl --user daemon-reload
    note "removed $UNIT_DIR/$UNIT_NAME"
    exit 0
fi

[ -f "$TEMPLATE" ] || die "missing template: $TEMPLATE"
[ -f "$SERVER_PY" ] || die "missing server: $SERVER_PY"

# --- Where the unit would never start -------------------------------------
#
# graphical-session.target is not started by systemd itself; the desktop
# environment has to pull it in. GNOME, KDE and every session launched through
# uwsm do. A bare sway or i3 started from a TTY does not, and the unit would
# then sit enabled and never run -- the panel permanently offline, with nothing
# in any log to explain it, which is indistinguishable from the PC being off.
if ! systemctl --user is-active --quiet graphical-session.target; then
    die "graphical-session.target is not active in this session, so an enabled unit would never start.
    Log in graphically first, or start your compositor through uwsm (https://github.com/Vladimir-csp/uwsm),
    which is what pulls graphical-session.target in for sway, i3, Hyprland and the like."
fi

# --- Where a system-scoped copy already answers ----------------------------
#
# A desk-panel.service in /etc/systemd/system answers at boot with nobody logged
# in, and it answers on the same port -- so the user unit would fail to bind and
# the panel would look perfect while reporting the wrong thing entirely.
if systemctl list-unit-files --type=service --no-legend 2>/dev/null | grep -q '^desk-panel'; then
    die "a system-scoped desk-panel unit exists; it answers with nobody logged in.
    Remove it (sudo systemctl disable --now desk-panel) before installing this one -- see
    docs/adr/0010-login-signal-is-session-scoped.md."
fi

# --- The interpreter -------------------------------------------------------
if [ -n "$PYTHON" ]; then
    command -v "$PYTHON" >/dev/null 2>&1 || die "no such interpreter: $PYTHON"
else
    PYTHON=$(command -v python3 || true)
    [ -n "$PYTHON" ] || die "no python3 on PATH; server/CLAUDE.md requires 3.11 or newer"
fi
# Absolute, because a unit file has no PATH worth relying on.
PYTHON=$(command -v "$PYTHON")
case "$PYTHON" in /*) ;; *) PYTHON="$PWD/$PYTHON" ;; esac
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "$PYTHON is older than 3.11 (server/CLAUDE.md)"

# --- The config ------------------------------------------------------------
#
# Absolute, always: a unit starts in the user manager's working directory, where
# a relative path resolves to something else entirely. server.py's
# config_search_paths documents the same contract for all three launchers.
if [ -n "$CONFIG" ]; then
    case "$CONFIG" in /*) ;; *) CONFIG="$PWD/$CONFIG" ;; esac
    [ -f "$CONFIG" ] || die "no such config: $CONFIG"
else
    for candidate in \
        "$SCRIPT_DIR/config.toml" \
        "$SCRIPT_DIR/config.json" \
        "${XDG_CONFIG_HOME:-$HOME/.config}/desk-panel/config.toml" \
        "${XDG_CONFIG_HOME:-$HOME/.config}/desk-panel/config.json"
    do
        [ -f "$candidate" ] || continue
        CONFIG=$candidate
        break
    done
    [ -n "$CONFIG" ] || die "no config found. Copy $SCRIPT_DIR/config.example.toml to $SCRIPT_DIR/config.toml first
    (a missing config is fatal to the server, so installing without one buys a restart loop)."
fi

step "Checking the config"
"$PYTHON" "$SERVER_PY" --config "$CONFIG" --check-only || die "the config does not load; fix it before installing"

# --- Render and install ----------------------------------------------------
#
# A path is not inert in a sed replacement: `&` stands for the whole match, `|`
# would end the expression, and a backslash escapes whatever follows. A repo at
# ~/proj&panel would otherwise render an ExecStart with the placeholder's own
# text spliced into it, install cleanly, and fail at start. Nobody has such a
# path today, which is exactly why nobody would look here when they did.
# (The template quotes each value, which is the other half -- a path with a
# space in it.)
sed_escape() {
    # One backslash before the match, not two, and the review caught the
    # difference. The first cut wrote the replacement as `\\\\&`, which sed
    # reads as two literal backslashes followed by the match -- so the escaped
    # path carried a stray backslash into the outer `s|@PYTHON@|...|`, and
    # /home/me/proj&panel rendered as /home/me/proj\@PYTHON@panel: the
    # placeholder's own text spliced into the value meant to replace it. A `|`
    # was worse -- the outer expression aborted with "unknown option to 's'"
    # after the redirection had already truncated the unit file, leaving a
    # zero-byte unit behind. A guard that produced the corruption it was added
    # to prevent. Verified with all three characters before and after.
    printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'
}

step "Writing $UNIT_DIR/$UNIT_NAME"
mkdir -p "$UNIT_DIR"
sed -e "s|@PYTHON@|$(sed_escape "$PYTHON")|g" \
    -e "s|@SERVER_PY@|$(sed_escape "$SERVER_PY")|g" \
    -e "s|@CONFIG@|$(sed_escape "$CONFIG")|g" \
    -e "s|@REPO@|$(sed_escape "$REPO_ROOT")|g" \
    "$TEMPLATE" > "$UNIT_DIR/$UNIT_NAME"
note "python  $PYTHON"
note "server  $SERVER_PY"
note "config  $CONFIG"

systemctl --user daemon-reload

if [ "$START" = yes ]; then
    step "Enabling and starting"
    systemctl --user enable --now "$UNIT_NAME"
else
    step "Enabling (not starting; it starts at your next graphical login)"
    systemctl --user enable "$UNIT_NAME"
fi

# --- What is left for a human ----------------------------------------------
step "Installed"
note "status   systemctl --user status $UNIT_NAME"
note "log      journalctl --user -u $UNIT_NAME -f"
note "remove   sh server/install_user_unit.sh --uninstall"

# The firewall is detected and described, never configured. Desktop distros
# usually ship no inbound filter at all, and when they do it is firewalld *or*
# ufw *or* nftables -- three tools with three vocabularies, and a script that
# picked one would be editing a stranger's security policy on their behalf.
PORT=$("$PYTHON" -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from server.server import load_config
print(load_config(Path(sys.argv[2])).get("port", 8777))
' "$REPO_ROOT" "$CONFIG" 2>/dev/null) || PORT=
# The port is only used in a sentence a human reads, so a config this cannot
# parse costs the sentence its accuracy and nothing else -- the server itself
# has already loaded the same file successfully by this point.
[ -n "$PORT" ] || PORT=8777

step "The firewall, if this machine has one"
# Read the state where it can be read, and **say so where it cannot**. The first
# cut of this block ran `ufw status` as the logged-in user, which exits 1 with
# "You need to be root to run this script" on stderr -- so on the machine this
# was written on, which has ufw installed *and* a rule for the phone's subnet,
# it printed "no inbound filter found". A firewall that is reported absent is
# worse than one reported unknown: the panel then reads offline for ever and the
# one place it was going to be looked for has said there is nothing to look at.
if command -v ufw >/dev/null 2>&1; then
    if ufw_state=$(ufw status 2>/dev/null); then
        case "$ufw_state" in
            *"Status: active"*) note "ufw is active." ;;
            *) note "ufw is installed and inactive, so it is not filtering anything." ;;
        esac
    else
        note "ufw is installed; its state cannot be read without root (sudo ufw status)."
    fi
    note "If it is active, the rule is scoped to where the phone actually is -- which may be"
    note "another subnet if the phone is behind a router's NAT:"
    note "  sudo ufw allow from <phone-subnet> to any port $PORT proto tcp"
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    note "firewalld is running, in zone $(firewall-cmd --get-default-zone 2>/dev/null). Add the port there:"
    note "  sudo firewall-cmd --permanent --add-port=$PORT/tcp && sudo firewall-cmd --reload"
elif command -v nft >/dev/null 2>&1; then
    note "nftables is installed; its ruleset needs root to read (sudo nft list ruleset)."
    note "If anything hooks input, allow tcp dport $PORT from the phone's subnet in that table."
else
    note "none of ufw, firewalld or nftables is installed, which is the usual desktop case."
fi
note "Whatever it says, prove it from the phone's subnet rather than from localhost:"
# --port, because probe.py defaults to 8777 and this server may not be on it.
# Printing the right ufw rule beside a proof that connects to the wrong port is
# how somebody spends an evening on a firewall that was never in the way.
note "  python server/probe.py --host <this-pc-ip> --port $PORT --expect up"
