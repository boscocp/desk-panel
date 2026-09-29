#!/bin/sh
# Install the desk-panel server as a per-user LaunchAgent limited to the Aqua
# session (T3.10). The macOS sibling of install_task.ps1 and
# install_user_unit.sh, and it makes the same promise: the server is launched
# by, and dies with, the graphical session of a human user, so "it answers"
# means "somebody is logged in at that screen".
#
#   sh server/install_agent.sh                 install and start
#   sh server/install_agent.sh --config PATH   use a config other than the found one
#   sh server/install_agent.sh --python PATH   use an interpreter other than python3 on PATH
#   sh server/install_agent.sh --no-start      write the plist, load it at next login
#   sh server/install_agent.sh --uninstall     unload and remove the agent
#
# POSIX sh, so the /bin/sh macOS ships (zsh in sh mode) runs it unchanged.
#
# What it refuses matters more than what it does. It will not install for root,
# it will not install beside a LaunchDaemon or a /Library/LaunchAgents copy of
# the same label, and it will not bootstrap from outside the Aqua session --
# each of those produces a server that answers with nobody at the desk, the
# failure docs/adr/0010-login-signal-is-session-scoped.md exists to forbid.

set -eu

LABEL=dev.bosco.deskpanel
AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENT_DIR/$LABEL.plist"
LOG="$HOME/Library/Logs/desk-panel.log"
# shellcheck disable=SC1007
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TEMPLATE="$SCRIPT_DIR/$LABEL.plist.in"
SERVER_PY="$SCRIPT_DIR/server.py"

CONFIG=
PYTHON=${DESK_PANEL_PYTHON:-}
START=yes
UNINSTALL=no

step() { printf '==> %s\n' "$1"; }
note() { printf '    %s\n' "$1"; }
die() { printf 'install_agent.sh: %s\n' "$1" >&2; exit 1; }

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

[ "$(uname -s)" = Darwin ] || die "this installs a macOS LaunchAgent; on Linux use install_user_unit.sh"

# Root has no Aqua session of its own, and `sudo sh install_agent.sh` would
# write into /var/root/Library/LaunchAgents where nothing ever loads it.
[ "$(id -u)" -ne 0 ] || die "do not run this as root or under sudo: it installs an agent into your own session"

DOMAIN="gui/$(id -u)"

if [ "$UNINSTALL" = yes ]; then
    step "Removing $LABEL"
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    rm -f "$PLIST"
    note "removed $PLIST"
    exit 0
fi

[ -f "$TEMPLATE" ] || die "missing template: $TEMPLATE"
[ -f "$SERVER_PY" ] || die "missing server: $SERVER_PY"

# --- Where a system-scoped copy already answers ----------------------------
#
# A LaunchDaemon loads at boot as root with nobody logged in, and a
# /Library/LaunchAgents copy loads for *every* user's login, the wrong one
# included. Either would hold the port and make this agent's server fail to
# bind, while the panel looked perfect.
for other in "/Library/LaunchDaemons/$LABEL.plist" "/Library/LaunchAgents/$LABEL.plist"; do
    [ ! -e "$other" ] || die "$other exists; it answers without this user's login.
    Remove it (sudo launchctl bootout system/$LABEL; sudo rm $other) first -- see
    docs/adr/0010-login-signal-is-session-scoped.md."
done

# --- The session this runs in ----------------------------------------------
#
# Bootstrapping into gui/<uid> from an SSH session works when the user also
# happens to be logged in at the screen, and fails with an opaque "Bootstrap
# failed: 5" when they are not. Refusing here says why instead. --no-start
# needs no session: the plist is picked up at the next GUI login.
if [ "$START" = yes ]; then
    session=$(launchctl managername 2>/dev/null || true)
    [ "$session" = Aqua ] || die "this shell is in the '${session:-unknown}' session, not Aqua.
    Run it from Terminal at the Mac's screen, or pass --no-start to load it at the next login."
fi

# --- The interpreter -------------------------------------------------------
if [ -n "$PYTHON" ]; then
    command -v "$PYTHON" >/dev/null 2>&1 || die "no such interpreter: $PYTHON"
else
    PYTHON=$(command -v python3 || true)
    [ -n "$PYTHON" ] || die "no python3 on PATH; server/CLAUDE.md requires 3.11 or newer"
fi
# Absolute, because launchd starts the agent with a PATH of /usr/bin:/bin.
PYTHON=$(command -v "$PYTHON")
case "$PYTHON" in /*) ;; *) PYTHON="$PWD/$PYTHON" ;; esac
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "$PYTHON is older than 3.11 (server/CLAUDE.md). /usr/bin/python3 is 3.9; install a newer one"

# --- The config ------------------------------------------------------------
if [ -n "$CONFIG" ]; then
    case "$CONFIG" in /*) ;; *) CONFIG="$PWD/$CONFIG" ;; esac
    [ -f "$CONFIG" ] || die "no such config: $CONFIG"
else
    for candidate in "$SCRIPT_DIR/config.toml" "$SCRIPT_DIR/config.json"; do
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
# Rendered by Python rather than sed, because a plist is XML: a path with `&`
# or `<` in it has to be escaped for XML, and sed would additionally need its
# own escaping for `&`, `|` and `\` in the replacement -- two escaping layers
# the Linux installer's comments show are easy to get wrong. plutil -lint
# afterwards is the proof the result is a plist.
step "Writing $PLIST"
mkdir -p "$AGENT_DIR" "$(dirname -- "$LOG")"
"$PYTHON" - "$TEMPLATE" "$PLIST" "$PYTHON" "$SERVER_PY" "$CONFIG" "$LOG" <<'EOF'
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

template, out, python, server, config, log = sys.argv[1:]
text = Path(template).read_text(encoding="utf-8")
for key, value in (("@PYTHON@", python), ("@SERVER_PY@", server),
                   ("@CONFIG@", config), ("@LOG@", log)):
    text = text.replace(f"<string>{key}</string>", f"<string>{escape(value)}</string>")
leftover = re.search(r"<string>@[A-Z_]+@</string>", text)
if leftover:
    raise SystemExit(f"unrendered placeholder: {leftover.group(0)}")
Path(out).write_text(text, encoding="utf-8")
EOF
plutil -lint "$PLIST" >/dev/null || die "the rendered plist does not lint: $PLIST"
note "python  $PYTHON"
note "server  $SERVER_PY"
note "config  $CONFIG"
note "log     $LOG"

if [ "$START" = yes ]; then
    step "Loading into $DOMAIN"
    # bootout first: bootstrap refuses a label that is already loaded, and a
    # re-install must pick up the new plist rather than keep the old one.
    #
    # bootout returns before launchd has let go of the label, and a bootstrap
    # that lands in that window fails with "Bootstrap failed: 5: Input/output
    # error" -- after the old job is gone, so a re-install that loses the race
    # leaves the panel with no server at all. Seen on the owner's first re-run
    # (2026-09-29); every earlier run had won it by luck. So wait until the
    # label is really gone, and give the bootstrap one more try.
    if launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1; then
        tries=0
        while [ $tries -lt 20 ] && launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; do
            sleep 0.5
            tries=$((tries + 1))
        done
    fi
    if ! launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
        sleep 2
        launchctl bootstrap "$DOMAIN" "$PLIST" \
            || die "launchctl bootstrap failed twice; the agent is NOT loaded. Retry: launchctl bootstrap $DOMAIN $PLIST"
    fi
else
    step "Written (not loaded; launchd loads it at your next graphical login)"
fi

# --- What is left for a human ----------------------------------------------
step "Installed"
note "status   launchctl print $DOMAIN/$LABEL"
note "log      tail -f $LOG"
note "remove   sh server/install_agent.sh --uninstall"

# The Application Firewall is described, never configured. It is off by
# default, it is per-binary rather than per-port, and its prompt names
# "python3", not desk-panel -- so a server that answers on localhost and not
# from the phone is usually a firewall the owner never knowingly turned on.
step "The firewall, if this Mac has it on"
fw=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null || true)
# The binary that listens is not the one in ProgramArguments. A framework
# Python (Homebrew's, python.org's) re-execs into .../Resources/Python.app, and
# that is the name the firewall lists -- measured on the first install, where
# naming python3.13 would have sent the owner to allow a binary that never
# opens a socket. So ask the running process; before it runs, say less.
#
# Asked once the socket is open, not straight after bootstrap: the second run
# of this script asked immediately, caught the process before its re-exec, and
# named /opt/homebrew/bin/python3 anyway.
listener=
# Only when this run loaded it: with --no-start whatever is loaded is the
# previous install, and naming its binary would describe the wrong plist.
pid=
[ "$START" != yes ] || pid=$(launchctl print "$DOMAIN/$LABEL" 2>/dev/null | sed -n 's/^	pid = //p' | head -n 1)
if [ -n "$pid" ]; then
    tries=0
    while [ $tries -lt 20 ] && ! lsof -a -p "$pid" -iTCP -sTCP:LISTEN >/dev/null 2>&1; do
        sleep 0.5
        tries=$((tries + 1))
    done
    lsof -a -p "$pid" -iTCP -sTCP:LISTEN >/dev/null 2>&1 && listener=$(ps -o comm= -p "$pid" 2>/dev/null || true)
fi
case "$fw" in
    *enabled*)
        note "The Application Firewall is on. It allows or blocks by binary, and the one"
        if [ -n "$listener" ]; then
            note "listening is $listener."
        else
            note "listening is whatever $PYTHON execs into -- see ps once the agent runs."
        fi
        note "Allow it in System Settings > Network > Firewall > Options. A Homebrew upgrade"
        note "moves that binary, and the allowance has to be given again." ;;
    *disabled*) note "The Application Firewall is off, so nothing is filtering inbound connections." ;;
    *) note "Could not read the Application Firewall's state." ;;
esac
note "Whatever it says, prove it from the phone's subnet rather than from localhost:"
note "  python3 server/probe.py --host <this-mac-ip> --expect up"
