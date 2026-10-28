# Network allow-list

The desk has two layers of network control:

1. **In code:** `collector/desk/net.py` refuses any URL whose host is not in `ALLOWED_HOST_SUFFIXES` (the same list as
   `allowlist.txt`). This is always on.
2. **On the network (recommended):** run the collector where DNS and outbound traffic only allow the hosts in
   `allowlist.txt`, for example a container whose only DNS server is dnsmasq with
   `dnsmasq-allowlist.conf.example`, plus a packet filter (iptables/nftables/pf) that drops everything else. Point
   `DESK_WRAPPER` (see `run/run-collector.sh`) at a command that runs the collector inside that container.

**Canary:** every run tries to resolve `example.com`, which is not on the list, and `STATUS.md` says whether it was
blocked. The canary tests layer 2: without a network allow-list it resolves, STATUS says so in bold, and the review
verdict is FAIL. That is on purpose: the desk is meant to run behind the firewall.

The list is US-only on purpose (US government data plus two US market-data APIs). Keep `allowlist.txt`, `net.py` and
your firewall config in sync when you add a source.
