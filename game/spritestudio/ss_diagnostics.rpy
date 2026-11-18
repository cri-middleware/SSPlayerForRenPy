# SSPlayer diagnostics — a quick "is it working / what's available" check.
#
# In developer mode, prints a one-line summary at game start so you immediately
# know the native runtime loaded and which .ssab packs were discovered. Also
# exposes `ss_diagnostics()` to call from the console (Shift+O) any time.
# Drop this file to remove it (it never affects release behaviour).

init python:

    def ss_diagnostics():
        """Return {'runtime': bool, 'packs': [name, ...]} describing the install."""
        info = {"runtime": False, "packs": []}
        try:
            info["runtime"] = _SS_LIB is not None
        except Exception:
            pass
        try:
            # Every pack, as the Shift+B browser lists them: ss_list_assets()
            # leaves out one another pack plays as an instance, and Ringo_tyu
            # plays Ringo.
            info["packs"] = sorted(r.stem for r in _ss_get_index().records())
        except Exception:
            pass
        return info

    if config.developer and hasattr(config, "start_callbacks"):
        # print(), not renpy.log(): renpy.log returns immediately unless the
        # project sets config.log, so the summary this file exists to give was
        # going nowhere in a stock project. stdout is where the auto importer
        # already reports, so both land in the same place.
        def _ss_log_diagnostics():
            try:
                info = ss_diagnostics()
                packs = info["packs"]
                preview = ", ".join(packs[:8]) + (" ..." if len(packs) > 8 else "")
                print("[SSPlayer] native runtime %s | %d pack(s)%s"
                      % ("loaded" if info["runtime"] else "NOT loaded",
                         len(packs), (": " + preview) if packs else ""))
            except Exception as e:
                print("[SSPlayer] diagnostics failed: %r" % (e,))

        config.start_callbacks.append(_ss_log_diagnostics)
