#!/usr/bin/env bash
cd /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/retro
w(){ until [ $(ls $(printf 'out/%s.exit ' "$@") 2>/dev/null | wc -l) -ge $# ]; do sleep 20; done; }
w w1-mgr1 w1-mgr2 w1-mgr3 w1-mgr4; echo "mgr ledgers done $(date -u +%H:%M)"
tools/run.sh w2-manager-side briefs/w2-manager-side.md; echo "manager-side done $(cat out/w2-manager-side.exit)"
for n in retro principles structure; do tools/run.sh w3-$n briefs/w3-$n.md & done; wait; echo "w3 done $(cat out/w3-*.exit | tr '\n' ' ')"
tools/run.sh w4-critic briefs/w4-critic.md xhigh; echo "critic done $(cat out/w4-critic.exit)"
