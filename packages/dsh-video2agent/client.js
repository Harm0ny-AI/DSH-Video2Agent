window.__ModuleLoader__.load({
  id: 'dsh-video2agent',
  factory: (require) => {
    const React = require('react')
    const h = React.createElement

    const CSS = [
      '[data-vp-card]{box-sizing:border-box;width:100%;max-width:var(--dsh-composer-card-max-width,748px);border:1px solid var(--vp-glass-line);background:var(--vp-glass-bg);backdrop-filter:blur(24px) saturate(180%);border-radius:var(--vp-glass-radius,20px);padding:12px 14px;margin:6px 0;font-size:13px;line-height:1.5;color:var(--dsw-alias-label-primary,#1f1f1c);box-shadow:0 14px 34px rgba(25,35,30,.10),0 1px 0 rgba(255,255,255,.9) inset;animation:vp-window-in .32s cubic-bezier(.22,1,.36,1);transition:box-shadow .28s ease,transform .24s ease,opacity .2s ease;}',
      '[data-vp-card][data-vp-done]{border:1px solid var(--vp-glass-line);background:var(--vp-glass-bg);backdrop-filter:blur(24px) saturate(180%);border-radius:20px;padding:12px 14px;box-shadow:0 14px 34px rgba(25,35,30,.10),0 1px 0 rgba(255,255,255,.9) inset;max-width:var(--dsh-composer-card-max-width,748px);margin:6px 0;}',
      '[data-vp-done-main]{display:flex;align-items:center;gap:12px;min-width:0;}',
      '[data-vp-done-badge]{flex:none;width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--vp-ok);color:#fff;box-shadow:0 4px 12px var(--vp-ok-soft);}',
      '[data-vp-done-badge] svg{width:22px;height:22px;overflow:visible;}',
      '[data-vp-done-badge] path{fill:none;stroke:currentColor;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;}',
      '[data-vp-done-body]{min-width:0;flex:1;}',
      '[data-vp-done-title]{font-size:15.5px;font-weight:680;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--dsw-alias-label-primary,#1f1f1c);}',
      '[data-vp-done-sub]{font-size:11.5px;line-height:1.35;color:#1a7f37;margin-top:2px;}',
      '[data-vp-done-meta]{display:flex;gap:9px;flex-wrap:wrap;margin-top:7px;font-size:11px;color:var(--vp-muted,#63605a);}',
      '[data-vp-done-foot]{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:8px;padding-top:7px;border-top:1px solid rgba(120,120,120,.12);font-size:11px;color:var(--vp-muted,#63605a);}',
      '[data-vp-done-foot] [data-vp-mono]{overflow:hidden;text-overflow:ellipsis;}',
      '[data-vp-head]{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:7px;}',
      '[data-vp-card],[data-vp-preview],[data-vp-live],[data-vp-settings],[data-vp-picker],[data-vp-search],[data-vp-queue]{--vp-accent:#0a84ff;--vp-accent-strong:#0066d6;--vp-accent-tint:#5aa9ff;--vp-accent-soft:rgba(10,132,255,.10);--vp-accent-line:rgba(10,132,255,.22);--vp-ok:#2ea043;--vp-ok-soft:rgba(46,160,67,.22);--vp-muted:#63605a}',
      '[data-vp-kicker]{display:flex;align-items:center;gap:7px;font-size:10px;letter-spacing:.11em;text-transform:uppercase;color:var(--vp-accent);font-weight:650;}',
      '[data-vp-dot]{width:6px;height:6px;border-radius:50%;background:var(--vp-accent);flex:none;}',
      '[data-vp-dot="run"]{animation:vp-pulse 1.6s ease-in-out infinite;}',
      '[data-vp-dot="ok"]{background:var(--vp-accent);}',
      '[data-vp-dot="err"]{background:#b4493f;}',
      '[data-vp-title]{font-size:13.5px;font-weight:650;line-height:1.42;margin-bottom:2px;overflow-wrap:anywhere;}',
      '[data-vp-muted]{color:var(--vp-muted,#63605a);font-size:11px;font-variant-numeric:tabular-nums;}',
      '[data-vp-meta]{color:var(--vp-muted,#63605a);font-size:11px;display:flex;gap:9px;flex-wrap:wrap;font-variant-numeric:tabular-nums;}',
      '[data-vp-meta] b{color:var(--dsw-alias-label-secondary,#555);font-weight:600;}',
      '[data-vp-chip]{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--vp-accent);background:var(--vp-accent-soft);border-radius:999px;padding:2px 7px;font-size:10.5px;white-space:nowrap;}',
      '[data-vp-mono]{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10.5px;overflow-wrap:anywhere;}',
      '[data-vp-headline]{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin:9px 0 2px;}',
      '[data-vp-pct]{font-size:22px;font-weight:600;line-height:1;letter-spacing:-.04em;font-variant-numeric:tabular-nums;}',
      '[data-vp-pct] small{font-size:10.5px;font-weight:500;color:var(--vp-muted,#63605a);margin-left:2px;}',
      '[data-vp-stage]{color:var(--dsw-alias-label-secondary,#555);font-size:11px;text-align:right;min-width:0;}',
      '[data-vp-bar]{position:relative;height:6px;background:var(--vp-accent-soft);border-radius:99px;overflow:hidden;margin:9px 0 10px;}',
      '[data-vp-bar] span{display:block;height:100%;background:linear-gradient(90deg,var(--vp-accent),var(--vp-accent-tint));border-radius:99px;transition:width .5s cubic-bezier(.22,1,.36,1);}',
      '[data-vp-steps]{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:9px;}',
      '[data-vp-step]{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--vp-muted,#63605a);border:1px solid transparent;border-radius:7px;padding:2px 6px;white-space:nowrap;}',
      '[data-vp-step]:before{content:"";width:5px;height:5px;border-radius:50%;background:rgba(120,120,120,.28);flex:none;}',
      '[data-vp-step="done"]{color:var(--dsw-alias-label-secondary,#555);}',
      '[data-vp-step="done"]:before{background:var(--vp-accent);}',
      '[data-vp-step="active"]{color:var(--vp-accent);font-weight:650;background:var(--vp-accent-soft);border-color:var(--vp-accent-line);}',
      '[data-vp-step="active"]:before{background:var(--vp-accent);animation:vp-pulse 1.6s ease-in-out infinite;}',
      '[data-vp-note]{color:var(--dsw-alias-label-secondary,#555);font-size:11.5px;line-height:1.45;overflow-wrap:anywhere;}',
      '[data-vp-foot]{display:flex;justify-content:space-between;align-items:center;gap:10px;border-top:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.16));margin-top:9px;padding-top:8px;flex-wrap:wrap;}',
      '[data-vp-actions]{display:flex;gap:7px;flex-wrap:wrap;}',
      '[data-vp-btn]{border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.28));background:transparent;color:inherit;border-radius:7px;padding:4px 9px;font:11.5px/1.2 inherit;cursor:pointer;}',
      '[data-vp-btn]:hover{border-color:var(--vp-accent);color:var(--vp-accent);}',
      '[data-vp-btn="primary"]{background:var(--vp-accent);border-color:var(--vp-accent);color:#fff;font-weight:600;}',
      '[data-vp-btn="primary"]:hover{background:var(--vp-accent-strong);color:#fff;}',
      '[data-vp-row]{display:flex;gap:9px;align-items:flex-start;padding:5px 0;}',
      '[data-vp-time]{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10.5px;color:var(--vp-accent);background:var(--vp-accent-soft);border-radius:5px;padding:1px 5px;flex:none;margin-top:2px;font-variant-numeric:tabular-nums;}',
      '[data-vp-rowmain]{min-width:0;flex:1;}',
      '[data-vp-rowtile]{width:96px;flex:none;margin-right:10px;}',
      '[data-vp-rowtile] [data-vp-tile-cover]{border-radius:7px;}',
      '[data-vp-rowtitle]{line-height:1.45;overflow-wrap:anywhere;}',
      '[data-vp-rowmeta]{color:var(--vp-muted,#63605a);font-size:10.5px;margin-top:2px;display:flex;gap:8px;flex-wrap:wrap;}',
      '[data-vp-thumbs]{display:flex;gap:8px;margin:8px 0 3px;flex-wrap:wrap;}',
      '[data-vp-thumb]{width:108px;height:61px;border-radius:8px;object-fit:cover;background:rgba(128,128,128,.08);border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.16));}',
      '[data-vp-warn]{color:#8a6a2f;background:rgba(185,139,61,.10);border:1px solid rgba(185,139,61,.28);border-radius:8px;padding:7px 9px;font-size:11.5px;margin-top:8px;overflow-wrap:anywhere;}',
      '[data-vp-warn="err"]{color:#a03a31;background:rgba(180,73,63,.08);border-color:rgba(180,73,63,.24);}',
      '[data-vp-pre]{white-space:pre-wrap;word-break:break-word;max-height:200px;overflow:auto;font:11px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--dsw-alias-label-secondary,#555);margin:6px 0 0;}',
      '[data-vp-linkrow]{display:flex;gap:11px;align-items:flex-start;}',
      '[data-vp-cover]{width:104px;height:58px;border-radius:8px;object-fit:cover;background:rgba(128,128,128,.08);flex:none;}',
      '[data-vp-linkmain]{min-width:0;flex:1;}',
      '[data-vp-url]{color:var(--vp-muted,#63605a);font-size:10.5px;word-break:break-all;margin-top:4px;}',
      '[data-vp-live]{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;position:relative;box-sizing:border-box;width:100%;max-width:var(--dsh-composer-card-max-width,748px);margin:0 auto 9px;border:1px solid var(--vp-glass-line);background:var(--vp-glass-bg);backdrop-filter:blur(30px) saturate(190%);border-radius:var(--vp-glass-radius);padding:10px 13px;color:var(--dsw-alias-label-primary,#1f1f1c);box-shadow:0 18px 46px rgba(25,35,30,.12),0 1px 0 rgba(255,255,255,.9) inset;animation:vp-window-in .42s cubic-bezier(.22,1,.36,1);transition:box-shadow .3s ease,transform .22s ease,opacity .2s ease;}',
      '[data-vp-live]:before{content:"";position:absolute;left:14px;right:14px;top:0;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.95),transparent);}',
      '[data-vp-queue]{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;position:relative;box-sizing:border-box;flex:none;width:100%;max-width:var(--dsh-composer-card-max-width,748px);margin:0 auto 9px;border:1px solid var(--vp-glass-line,rgba(255,255,255,.58));background:var(--vp-glass-bg,linear-gradient(180deg,rgba(255,255,255,.92),rgba(255,255,255,.74)));backdrop-filter:blur(24px) saturate(180%);border-radius:var(--vp-glass-radius,20px);padding:10px 14px;color:var(--dsw-alias-label-primary,#1f1f1c);box-shadow:0 16px 40px rgba(25,35,30,.10),0 1px 0 rgba(255,255,255,.55) inset;animation:vp-window-in .34s cubic-bezier(.22,1,.36,1);transition:box-shadow .24s ease,transform .24s ease,opacity .2s ease;}',
      '[data-vp-queue]:before{content:"";position:absolute;left:14px;right:14px;top:0;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.85),transparent);}',
      '[data-vp-queue-head]{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--vp-muted,#63605a);margin-bottom:4px;}',
      '[data-vp-queue-head] b{font-size:12px;font-weight:600;color:inherit;}',
      '[data-vp-queue-sub]{font-size:10.5px;color:var(--vp-muted,#63605a);}',
      '[data-vp-queue-stop-error]{font-size:10.5px;color:#d93025;white-space:nowrap;}',
      '[data-vp-queue-collapse]{margin-left:auto;border:0;background:transparent;color:var(--vp-muted,#63605a);border-radius:7px;padding:3px 7px;font:10.5px/1.2 inherit;cursor:pointer;transition:background .16s ease,color .16s ease;}',
      '[data-vp-queue-collapse]:hover{background:rgba(128,128,128,.12);color:var(--vp-accent);}',
      // A 10-video batch used to grow past the top of the window: the table is
      // anchored above the composer, so the newest rows pushed everything up and
      // the first rows were off-screen. Cap the list and scroll inside it.
      '[data-vp-queue-rows]{display:flex;flex-direction:column;gap:2px;max-height:min(46vh,340px);overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;}',
      '[data-vp-queue-row]{display:grid;grid-template-columns:108px minmax(0,1fr) auto;align-items:center;gap:12px;min-height:72px;border-top:1px solid rgba(120,120,120,.10);font-size:12px;border-radius:10px;transition:background-color .18s ease,opacity .18s ease,transform .18s ease;}',
      '[data-vp-queue-row]:first-child{border-top:0;}',
      '[data-vp-queue-row]:hover{background:rgba(128,128,128,.05);}',
      '[data-vp-queue-cover]{width:96px;height:54px;border-radius:8px;object-fit:cover;background:linear-gradient(135deg,#2c2c2e,#545458);display:block;transition:width .2s ease,height .2s ease,border-radius .2s ease;}',
      '[data-vp-queue-ring-wrap]{position:relative;width:108px;height:66px;display:flex;align-items:center;justify-content:center;flex:none;}',
      '[data-vp-queue-ring]{position:absolute;inset:0;width:108px;height:66px;transform:none;overflow:visible;}',
      '[data-vp-queue-ring-track]{fill:none;stroke:var(--vp-accent-line);stroke-width:3.5;}',
      '[data-vp-queue-ring-value]{fill:none;stroke:var(--vp-accent);stroke-width:3.5;stroke-linecap:round;transition:stroke-dashoffset .85s cubic-bezier(.22,1,.36,1),stroke .3s ease;}',
      '[data-vp-queue-cover][data-active="on"]{width:96px;height:54px;border-radius:7px;box-shadow:0 5px 14px rgba(0,0,0,.16);}',
      '[data-vp-queue-cover][data-empty="on"]{display:flex;align-items:center;justify-content:center;font-size:18px;color:#d8d2c7;}',
      '[data-vp-queue-main]{display:flex;flex-direction:column;gap:2px;min-width:0;}',
      '[data-vp-queue-titleline]{display:flex;align-items:center;gap:6px;min-width:0;}',
      '[data-vp-queue-name]{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:inherit;font-weight:600;font-size:12px;}',
      '[data-vp-queue-meta]{font-size:10.5px;color:var(--vp-muted,#63605a);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '[data-vp-queue-state]{font-size:11px;color:var(--vp-muted,#63605a);white-space:nowrap;transition:color .18s ease;}',
      '[data-vp-queue-row][data-state="ok"] [data-vp-queue-state]{color:var(--vp-ok,#2ea043);}',
      '[data-vp-queue-row][data-state="muted"] [data-vp-queue-state]{opacity:.65;}',
      '[data-vp-queue-actions]{display:flex;justify-content:flex-end;}',
      '[data-vp-queue-tail]{display:flex;align-items:center;justify-content:flex-end;gap:6px;}',
      '[data-vp-queue-cancel]{border:1px solid rgba(120,120,120,.24);background:transparent;color:var(--vp-muted,#63605a);border-radius:6px;padding:2px 6px;font:10px/1.2 inherit;cursor:pointer;min-height:18px;transition:color .16s ease,border-color .16s ease,background .16s ease;}',
      '[data-vp-queue-cancel]:hover{color:#d93025;border-color:rgba(217,48,37,.35);}',
      '[data-vp-queue-clear]{margin-left:4px;border:0;background:transparent;color:var(--vp-muted,#63605a);border-radius:7px;padding:3px 7px;font:10.5px/1.2 inherit;cursor:pointer;transition:color .16s ease,background .16s ease;}',
      '[data-vp-queue-clear]:hover{color:#d93025;background:rgba(217,48,37,.08);}',
      '[data-vp-queue][data-vp-queue-collapsed]{padding:0;border-radius:14px;overflow:hidden;min-height:44px;flex:none;}',
      '[data-vp-queue-expand]{display:flex;align-items:center;gap:8px;width:100%;min-height:44px;border:0;background:transparent;color:inherit;font:inherit;padding:10px 12px;cursor:pointer;border-radius:14px;text-align:left;transition:background .16s ease;}',
      '[data-vp-queue-expand]:hover{background:rgba(128,128,128,.06);}',
      '[data-vp-queue-pill-dot]{width:7px;height:7px;border-radius:50%;background:var(--vp-accent);box-shadow:0 0 0 3px var(--vp-accent-soft);flex:none;}',
      '[data-vp-queue-pill-cover]{width:56px;height:32px;border-radius:5px;object-fit:cover;flex:none;background:rgba(128,128,128,.10);box-shadow:0 2px 8px rgba(0,0,0,.14);}',
      '[data-vp-queue-pill-state]{font-size:10.5px;color:var(--vp-muted,#63605a);}',
      '[data-vp-queue-pill-action]{margin-left:auto;font-size:10.5px;color:var(--vp-accent);}',
      '[data-vp-queue-pill-caret]{font-size:11px;line-height:1;color:var(--vp-accent);opacity:.8;}',
      '@media (max-width:620px){[data-vp-queue]{padding:7px 9px;}[data-vp-queue-row]{font-size:11px;grid-template-columns:88px minmax(0,1fr) auto;}[data-vp-queue-cover],[data-vp-queue-cover][data-active=\"on\"]{width:80px;height:45px;}[data-vp-queue-ring-wrap],[data-vp-queue-ring]{width:88px;height:54px;}[data-vp-queue-actions]{grid-column:2 / span 2;justify-content:flex-start;padding-bottom:4px;}}',
      '@media (prefers-reduced-motion:reduce){[data-vp-queue],[data-vp-queue-row],[data-vp-queue-expand]{animation:none!important;transition:none!important;}}',
            '[data-vp-live-main]{display:flex;align-items:center;gap:14px;min-width:0;}',
      '[data-vp-live-icon]{position:relative;width:84px;height:84px;flex:none;display:flex;align-items:center;justify-content:center;}',
      '[data-vp-live-icon] > svg:first-child{position:absolute;inset:0;width:84px;height:84px;transform:rotate(-90deg);overflow:visible;}',
      '[data-vp-live-cover]{width:64px;height:64px;border-radius:12px;object-fit:cover;background:rgba(128,128,128,.08);flex:none;box-shadow:0 5px 14px rgba(0,0,0,.18);}',
      '[data-vp-live-cover-empty]{display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#2c2c2e,#545458);box-shadow:0 5px 14px rgba(0,0,0,.18);border:1px solid rgba(255,255,255,.16);}',
      '[data-vp-live-play]{width:15px;height:15px;display:block;fill:rgba(255,255,255,.95);margin-left:2px;}',
      '[data-vp-live-ring-track]{fill:none;stroke:var(--vp-accent-line);stroke-width:3.5;}',
      '[data-vp-live-ring-value]{fill:none;stroke:var(--vp-accent);stroke-width:3.5;stroke-linecap:round;transition:stroke-dashoffset .85s cubic-bezier(.22,1,.36,1),stroke .3s ease;}',
      '[data-vp-live][data-phase="error"] [data-vp-live-ring-value]{stroke:#ff3b30;}',
      '[data-vp-live][data-phase="error"] [data-vp-live-ring-track]{stroke:rgba(255,59,48,.15);}',
      // Success is a semantic colour, not the theme accent: a finished job reads
      // the same way a green check does in a build log, whatever theme is chosen.
      '[data-vp-live][data-phase="ready"] [data-vp-live-ring-value]{stroke:var(--vp-ok);filter:drop-shadow(0 0 6px var(--vp-ok-soft));}',
      '[data-vp-live][data-phase="ready"] [data-vp-live-ring-track]{stroke:var(--vp-ok-soft);}',
      '[data-vp-live][data-phase="ready"] [data-vp-live-sub]{color:#1a7f37;}',
      '[data-vp-live-badge]{position:absolute;right:-1px;bottom:-1px;width:21px;height:21px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--vp-ok);color:#fff;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.22);}',
      '[data-vp-live-badge][data-kind="error"]{background:#ff3b30;}',
      // Cancelled is neutral, not success: a green check on a cancelled job lied.
      '[data-vp-live-badge][data-kind="canceled"]{background:#8e8e93;}',
      '[data-vp-live][data-phase="canceled"] [data-vp-live-ring-value]{stroke:#8e8e93;}',
      '[data-vp-live][data-phase="canceled"] [data-vp-live-ring-track]{stroke:rgba(142,142,147,.2);}',
      '[data-vp-live-badge] svg{width:11px;height:11px;display:block;overflow:visible;}',
      '[data-vp-live-badge] path{fill:none;stroke:currentColor;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;}',
      '[data-vp-live][data-phase="ready"] [data-vp-live-badge] path{stroke-dasharray:30;stroke-dashoffset:30;animation:vp-check-draw .35s .08s ease-out forwards;}',
      '[data-vp-live-body]{min-width:0;flex:1;}',
      '[data-vp-live-title]{font-size:15.5px;font-weight:680;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:-.02em;}',
      '[data-vp-live-sub]{font-size:11.5px;line-height:1.35;color:var(--vp-muted,#63605a);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;font-variant-numeric:tabular-nums;}',
      '[data-vp-live-meta]{font-size:10.5px;line-height:1.3;color:var(--vp-muted,#8a857a);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;}',
      '[data-vp-live][data-phase="error"] [data-vp-live-sub]{color:#c7352d;}',
      '[data-vp-live][data-leaving="true"]{opacity:0;transform:translateY(-3px) scale(.985);}',
      '@media (prefers-reduced-motion: reduce){[data-vp-live],[data-vp-live] *{animation:none!important;transition:none!important;}}',
      '@keyframes vp-check-draw{to{stroke-dashoffset:0}}',
      '[data-vp-live-focus]{display:flex;align-items:center;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid var(--vp-accent-soft);font-size:12px;line-height:1.35;color:var(--dsw-alias-label-secondary,#555);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '[data-vp-live-focus] b{color:var(--vp-accent);font-weight:650;font-variant-numeric:tabular-nums;}',
      '[data-vp-live-err]{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '[data-vp-live-retry]{flex:none;margin-left:auto;border:0;background:transparent;color:var(--vp-accent);font:11px/1.2 inherit;padding:2px 4px;border-radius:5px;cursor:pointer;}',
      '[data-vp-live-retry]:hover{background:var(--vp-accent-soft);}',
      '[data-vp-live-retry]:disabled{color:var(--vp-muted,#63605a);cursor:default;background:transparent;}',
      '[data-vp-live-close]{flex:none;border:0;background:transparent;color:var(--vp-muted,#63605a);font:11px/1.2 inherit;padding:2px 4px;border-radius:5px;cursor:pointer;}',
      '[data-vp-live-close]:hover{background:var(--vp-accent-soft);}',
      '[data-vp-live-focusdot]{width:5px;height:5px;border-radius:50%;background:var(--vp-accent);flex:none;animation:vp-pulse 1.8s ease-in-out infinite;}',
      // Closing state: the turn ended, so the card stops pulsing and settles.
      '[data-vp-live][data-phase="closing"]{opacity:.94;}',
      '[data-vp-live][data-phase="closing"] [data-vp-live-focusdot]{animation:none;background:#77746b;}',
  '[data-vp-live][data-phase="error"] [data-vp-live-focusdot]{animation:none;background:#d93025;}',
      '[data-vp-live][data-phase="closing"] [data-vp-live-ring-value]{stroke:#77746b;}',
      '@keyframes vp-window-in{from{opacity:0;transform:translateY(7px) scale(.985)}to{opacity:1;transform:translateY(0) scale(1)}}',
      '[data-vp-settings]{max-width:560px;padding:4px 2px 20px;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;color:var(--dsw-alias-label-primary,#1f1f1c);}',
      '[data-vp-settings-title]{font-size:20px;line-height:1.3;font-weight:650;margin:0 0 4px;letter-spacing:-.02em;}',
      '[data-vp-settings-note]{font-size:12px;line-height:1.5;color:var(--vp-muted,#63605a);margin:0 0 18px;}',
      // Bilibili login block: the primary path to subtitles, so it is not a row.
      '[data-vp-cloud],[data-vp-bili]{border:1px solid var(--vp-accent-line);border-radius:14px;padding:12px 14px;margin:0 0 16px;background:var(--vp-accent-soft);}',
      // No loading text or animation: keep the blue card shells and fill their
      // contents when the (cached or prefetched) read is available.
      '[data-vp-settings][data-loading] [data-vp-cloud],[data-vp-settings][data-loading] [data-vp-bili]{display:block!important;min-height:64px;}',
      '[data-vp-settings][data-loading] [data-vp-cloud] > *,[data-vp-settings][data-loading] [data-vp-bili] > *{visibility:hidden!important;}',
      // Cloud controls sit inside the blue card: tint them with the accent,
      // never a native white box, and keep them inside the card (border-box).
      '[data-vp-settings] input:not([type=checkbox]):not([type=color]):not([type=range]),[data-vp-settings] select{box-sizing:border-box!important;max-width:100%!important;background:rgba(10,132,255,.065)!important;color:inherit!important;border:1px solid rgba(10,132,255,.18)!important;border-radius:9px!important;box-shadow:none!important;outline:none!important;}',
      '[data-vp-settings] input:not([type=checkbox]):not([type=color]):not([type=range]):focus,[data-vp-settings] select:focus{border-color:var(--vp-accent)!important;box-shadow:inset 0 0 0 1px var(--vp-accent)!important;}',
      '[data-vp-settings] select option{background:#fff;color:#111;}',
      '[data-vp-bili-head]{display:flex;align-items:center;justify-content:space-between;gap:12px;}',
      '[data-vp-bili-title]{font-size:13px;font-weight:650;}',
      '[data-vp-bili-state]{font-size:11px;color:var(--vp-muted,#77746b);}',
      '[data-vp-bili-state="on"]{color:#1a7f37;}',
      '[data-vp-bili-state="err"]{color:#a03a31;font-weight:600;}',
      '[data-vp-bili-hint]{font-size:11.5px;line-height:1.5;color:var(--vp-muted,#77746b);margin-top:6px;}',
      '[data-vp-bili-qrbox]{display:flex;flex-direction:column;align-items:center;gap:6px;margin-top:10px;}',
      '[data-vp-bili-qr]{width:180px;height:180px;image-rendering:pixelated;border-radius:10px;background:#fff;padding:6px;border:1px solid rgba(128,128,128,.18);}',
      '[data-vp-bili-tip]{font-size:11px;color:var(--vp-muted,#77746b);}',
      '[data-vp-bili-actions]{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;}',
      '[data-vp-bili-btn]{border:1px solid var(--vp-accent);background:transparent;color:var(--vp-accent);border-radius:8px;padding:5px 10px;font:12px/1.2 inherit;cursor:pointer;}',
      '[data-vp-bili-btn]:hover{background:var(--vp-accent-soft);}',
      '[data-vp-bili-btn]:disabled{opacity:.6;cursor:default;}',
      '[data-vp-seg]{display:inline-flex;align-items:center;gap:2px;padding:2px;border:1px solid rgba(10,132,255,.16);border-radius:999px;background:rgba(10,132,255,.07);min-width:190px;}',
      '[data-vp-seg] button{flex:1;border:0;border-radius:999px;background:transparent;color:var(--vp-muted,#63605a);padding:5px 11px;font:12px/1.2 inherit;cursor:pointer;white-space:nowrap;}',
      '[data-vp-seg] button[data-on="1"]{background:var(--vp-accent);color:#fff;box-shadow:0 1px 4px rgba(10,132,255,.22);}',
      '[data-vp-seg] button:hover:not([data-on="1"]):not(:disabled){color:var(--vp-accent);}',
      '[data-vp-seg] button:disabled{opacity:.45;cursor:default;}',
      '[data-vp-site="cn"]{background:var(--vp-accent)!important;border-color:var(--vp-accent)!important;color:#fff!important;text-decoration:none;}',
      '[data-vp-site="cn"]:hover{filter:brightness(.94);}',
      '[data-vp-site="intl"]{background:rgba(127,127,127,.06)!important;border-color:var(--vp-glass-line)!important;color:var(--vp-muted,#63605a)!important;text-decoration:none;}',
      '[data-vp-site="intl"]:hover{background:var(--vp-accent-soft)!important;color:var(--vp-accent)!important;}',
      '[data-vp-settings-row]{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px;padding:12px 0;border-top:1px solid rgba(120,120,120,.12);font-size:13px;}',
      '[data-vp-settings-row] select{border:1px solid rgba(120,120,120,.22);border-radius:8px;background:transparent;color:inherit;padding:4px 8px;font:12px/1.4 inherit;}',
      '[data-vp-settings-row] input{width:16px;height:16px;accent-color:var(--vp-accent);}',
      '[data-vp-settings-row] input[type="range"]{width:180px;height:24px;accent-color:var(--vp-accent);cursor:pointer;}',
      '[data-vp-process-control]{display:flex;align-items:center;gap:10px;min-width:0;}',
      '[data-vp-process-value]{min-width:42px;text-align:right;font-variant-numeric:tabular-nums;font-size:14px;color:var(--dsw-alias-label-primary,#1f1f1c);}',
      '@media (max-width:620px){[data-vp-settings-row] input[type="range"]{width:130px;}}',
      '[data-vp-swatches]{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}',
      '[data-vp-swatch]{width:20px;height:20px;border-radius:50%;border:1px solid rgba(0,0,0,.10);padding:0;cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,.10);}',
      '[data-vp-swatch="on"]{outline:2px solid var(--vp-accent);outline-offset:2px;}',
      '[data-vp-color]{width:28px;height:22px;padding:0;border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.28));border-radius:6px;background:transparent;cursor:pointer;}',
      '[data-vp-colorlabel]{font-size:11px;color:var(--vp-muted,#77746b);margin-left:2px;}',
      '[data-vp-settings-note]{color:var(--vp-muted,#63605a);font-size:11.5px;line-height:1.5;margin:-4px 0 10px;}',
      '[data-vp-settings-save]{margin-top:18px;border:0;border-radius:9px;background:var(--vp-accent);color:#fff;padding:7px 14px;font:13px/1.2 inherit;font-weight:600;cursor:pointer;}',
      '[data-vp-settings-save]:hover{filter:brightness(.94);}',
      '[data-vp-settings-save]:active{transform:scale(.98);}',
      '[data-vp-settings-summary]{font-size:12px;line-height:1.5;color:var(--vp-muted,#63605a);}',
      // The environment card reuses the blue settings card shell ([data-vp-cloud]);
      // no separate border/padding rule: a leftover rule here overrode its border.
      '[data-vp-env-row]{min-width:0;}',
      // One glass material for the composer surfaces, so the link preview, the
      // processing card and the batch table read as the same object. The live
      // card keeps a stronger shadow (it is the active one).
      '[data-vp-card],[data-vp-preview],[data-vp-live],[data-vp-picker],[data-vp-search],[data-vp-queue]{--vp-glass-bg:linear-gradient(180deg,rgba(255,255,255,.92),rgba(255,255,255,.74));--vp-glass-line:rgba(255,255,255,.58);--vp-glass-radius:20px;}',
      '[data-vp-preview]{box-sizing:border-box;position:relative;width:100%;max-width:var(--dsh-composer-card-max-width,748px);margin:0 auto 9px;border:1px solid var(--vp-glass-line);background:var(--vp-glass-bg);backdrop-filter:blur(30px) saturate(190%);border-radius:var(--vp-glass-radius);padding:11px 14px;display:flex;gap:12px;align-items:center;color:var(--dsw-alias-label-primary,#1f1f1c);font-size:13px;box-shadow:0 10px 30px rgba(25,35,30,.09),0 1px 0 rgba(255,255,255,.9) inset;animation:vp-window-in .3s cubic-bezier(.22,1,.36,1);}',
      '[data-vp-preview]:before{content:"";position:absolute;left:14px;right:14px;top:0;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.95),transparent);}',
      '[data-vp-preview-cover]{position:absolute;inset:0;width:100%;height:100%;border-radius:12px;object-fit:cover;background:rgba(128,128,128,.08);}',
      '[data-vp-preview-cover][data-empty="on"]{display:flex;align-items:center;justify-content:center;font-size:18px;color:#9a968d;}',
      '[data-vp-preview-shot]{position:relative;width:132px;aspect-ratio:16/9;flex:none;border-radius:12px;overflow:hidden;box-shadow:0 6px 16px rgba(0,0,0,.14);}',
      '[data-vp-preview-main]{min-width:0;flex:1;}',
      '[data-vp-preview-title]{font-size:13.5px;font-weight:650;line-height:1.35;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:-.02em;}',
      '[data-vp-preview-meta]{color:var(--vp-muted,#63605a);font-size:11px;margin-top:3px;display:flex;gap:9px;flex-wrap:wrap;font-variant-numeric:tabular-nums;}',
      '[data-vp-preview-kicker]{color:var(--vp-accent);font-size:10px;letter-spacing:.08em;margin-bottom:2px;font-weight:650;}',
      // Narrow screens: give the title more room than the thumbnail.
      '@media (max-width:520px){[data-vp-preview]{padding:10px 12px;gap:10px;}[data-vp-preview-shot]{width:104px;}}',
      // --- Design system: one shell, one type scale, one button set -----------------
      // Every surface (chat card, dock strip, dock picker, link preview) shares these
      // tokens, so a new card only picks placement, not its own palette or radii.
      '[data-vp-card],[data-vp-live],[data-vp-picker],[data-vp-preview],[data-vp-settings]{'
      + '--vp-radius:18px;--vp-radius-sm:10px;--vp-pad:14px;--vp-gap:10px;'
      + '--vp-line:var(--dsw-alias-border-l2,rgba(128,128,128,.20));'
      + '--vp-surface:var(--dsw-alias-bg-elevated,rgba(255,255,255,.80));'
      + '--vp-shadow:0 10px 28px rgba(0,0,0,.07);'
      + '--vp-fs-title:14.5px;--vp-fs-body:13px;--vp-fs-meta:11.5px;--vp-fs-kicker:10px;'
      + '--vp-meta:var(--vp-muted,#63605a);}',
      '[data-vp-picker]{border:1px solid var(--vp-line);border-radius:var(--vp-radius);background:var(--vp-surface);box-shadow:var(--vp-shadow);padding:var(--vp-pad);}',
      '[data-vp-live],[data-vp-preview]{border-radius:var(--vp-radius);}',
      '[data-vp-title],[data-vp-preview-title],[data-vp-search-title]{font-size:var(--vp-fs-title);font-weight:650;letter-spacing:-.02em;line-height:1.35;}',
      '[data-vp-preview][data-vp-preview-compact]{padding:9px 14px;gap:11px;align-items:center;}',
      '[data-vp-preview-compact] [data-vp-preview-shot]{width:64px;border-radius:8px;box-shadow:none;}',
      '[data-vp-preview-compact] [data-vp-tile-duration]{font-size:9.5px;padding:2px 4px;right:3px;bottom:3px;}',
      '[data-vp-preview-compact-line]{display:flex;align-items:center;gap:8px;min-width:0;font-size:12.5px;}',
      '[data-vp-preview-next]{flex:none;font-size:10px;font-weight:650;letter-spacing:.08em;text-transform:uppercase;color:var(--vp-accent);}',
      '[data-vp-preview-compact-title]{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--dsw-alias-label-secondary,#4b4b47);}',
      '[data-vp-muted],[data-vp-preview-meta],[data-vp-rowmeta],[data-vp-tile-meta]{font-size:var(--vp-fs-meta);color:var(--vp-meta);}',
      '[data-vp-kicker],[data-vp-preview-kicker]{font-size:var(--vp-fs-kicker);letter-spacing:.11em;text-transform:uppercase;font-weight:650;color:var(--vp-accent);}',
      '[data-vp-btn],[data-vp-hold-start],[data-vp-hold-cancel],[data-vp-settings-save]{font:600 12.5px/1 inherit;border-radius:var(--vp-radius-sm);padding:9px 13px;cursor:pointer;transition:background .14s ease,border-color .14s ease;}',
      '[data-vp-btn],[data-vp-hold-cancel]{border:1px solid var(--vp-line);background:transparent;color:inherit;}',
      '[data-vp-btn]:hover,[data-vp-hold-cancel]:hover{border-color:var(--vp-accent);color:var(--vp-accent);}',
      '[data-vp-btn][data-vp-btn-tone="primary"],[data-vp-hold-start],[data-vp-settings-save]{border:1px solid transparent;background:var(--vp-accent);color:#08131f;}',
      '[data-vp-btn][data-vp-btn-tone="primary"]:hover,[data-vp-hold-start]:hover,[data-vp-settings-save]:hover{background:var(--vp-accent-strong);filter:none;}',
      '[data-vp-chip]{border-radius:999px;font-size:10.5px;font-weight:600;padding:2px 8px;background:var(--vp-accent-soft);color:var(--vp-accent);border:1px solid var(--vp-accent-line);}',
      '[data-vp-chip][data-vp-chip-tone="err"]{background:rgba(180,73,63,.10);border-color:rgba(180,73,63,.28);color:#a03a31;}',
      '[data-vp-remedy]{display:flex;gap:8px;margin-top:10px;padding:10px 12px;border-radius:var(--vp-radius-sm);background:rgba(128,128,128,.07);font-size:var(--vp-fs-meta);line-height:1.5;}',
      '[data-vp-remedy-label]{flex:none;font-weight:650;color:var(--vp-meta);}',
      '[data-vp-shot]{margin:0;position:relative;}',
      '[data-vp-shot-time]{position:absolute;right:6px;bottom:6px;background:rgba(0,0,0,.62);color:#fff;font-size:10.5px;line-height:1;padding:3px 5px;border-radius:5px;font-variant-numeric:tabular-nums;}',
      // Discovery shortlist in the dock: visible without expanding any tool call.
      // Same width as the processing card, but 25% shorter: the covers use a
      // 16:6.5 crop and the rows are tighter. Do not narrow this card — at 534px
      // it looked like a floating dialog instead of a dock card.
      '[data-vp-picker],[data-vp-search]{box-sizing:border-box;width:100%;max-width:var(--dsh-composer-card-max-width,748px);margin:0 auto 9px;border:1px solid var(--vp-glass-line);border-radius:var(--vp-glass-radius);background:var(--vp-glass-bg);backdrop-filter:blur(30px) saturate(190%);box-shadow:0 18px 46px rgba(25,35,30,.12),0 1px 0 rgba(255,255,255,.9) inset;padding:9px 12px 10px;animation:vp-window-in .32s cubic-bezier(.22,1,.36,1);transition:box-shadow .28s ease,transform .24s ease,opacity .2s ease;}',
      '[data-vp-picker][data-closing="true"]{opacity:0;transform:translateY(4px) scale(.99);transition:opacity .16s ease,transform .16s ease;pointer-events:none;}',
      '[data-vp-search-head]{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:6px;}',
      '[data-vp-search-title]{font-size:12px;font-weight:600;color:var(--dsw-alias-label-secondary,#4b4b47);}',
      '[data-vp-picker-close]{display:inline-flex;align-items:center;justify-content:center;min-width:28px;min-height:28px;border:0;background:transparent;color:#6b6862;font-size:18px;line-height:1;cursor:pointer;padding:4px 6px;border-radius:8px;}',
      '[data-vp-picker-close]:hover{background:rgba(128,128,128,.12);}',
      '[data-vp-picker-list]{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:2px 2px 4px;overflow:visible;}[data-vp-picker-list][data-count="1"]{grid-template-columns:minmax(0,320px);justify-content:center;}[data-vp-picker-list][data-count="2"]{grid-template-columns:repeat(2,minmax(0,1fr));}[data-vp-picker-list][data-count="3"]{grid-template-columns:repeat(3,minmax(0,1fr));}[data-vp-picker-list][data-count="4"],[data-vp-picker-list][data-count="5"],[data-vp-picker-list][data-count="6"],[data-vp-picker-list][data-count="7"],[data-vp-picker-list][data-count="8"]{grid-template-columns:repeat(4,minmax(0,1fr));}[data-vp-picker-list][data-count="9"],[data-vp-picker-list][data-count="10"]{grid-template-columns:repeat(5,minmax(0,1fr));}',
      '[data-vp-picker-item]{box-sizing:border-box;display:flex;flex-direction:column;gap:7px;width:100%;min-width:0;text-align:left;border:1px solid rgba(128,128,128,.14);border-radius:14px;padding:7px 7px 8px;background:transparent;cursor:pointer;position:relative;transition:border-color .14s ease,box-shadow .16s ease,transform .16s ease;}',
      '[data-vp-picker-item]:hover{border-color:var(--vp-accent);background:var(--vp-accent-soft);box-shadow:0 6px 18px rgba(0,0,0,.08);}',
      '[data-vp-picker-item]:focus-within{outline:2px solid var(--vp-accent);outline-offset:2px;}',
      '[data-vp-picker-item] [data-vp-tile-input]:focus-visible + [data-vp-tile-check]{box-shadow:0 0 0 2px #fff,0 0 0 4px var(--vp-accent);}',
      // Bilibili-style tile: 16:9 cover, duration pill, two-line title, up + date + views.
      '[data-vp-tile]{display:flex;flex-direction:column;gap:6px;min-width:0;}',
      '[data-vp-tile-cover]{position:relative;width:100%;aspect-ratio:16/6.5;border-radius:10px;overflow:hidden;background:linear-gradient(135deg,rgba(128,128,128,.14),rgba(128,128,128,.06));}',
      '[data-vp-tile-img]{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}',
      '[data-vp-tile-img][data-empty="on"]{display:flex;align-items:center;justify-content:center;font-size:22px;color:#9a968d;}',
      '[data-vp-tile-duration]{position:absolute;right:7px;bottom:7px;background:rgba(0,0,0,.62);color:#fff;font-size:11.5px;line-height:1;padding:4px 6px;border-radius:6px;font-variant-numeric:tabular-nums;}',
      '[data-vp-tile-check]{position:absolute;left:7px;top:7px;width:20px;height:20px;border-radius:999px;background:var(--vp-ok);color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,.28);}',
      '[data-vp-tile-check] svg{width:12px;height:12px;fill:none;stroke:#fff;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round;}',
      '[data-vp-tile-select]{position:absolute;left:7px;top:7px;width:20px;height:20px;z-index:2;}',
      '[data-vp-tile-select] [data-vp-tile-input]{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer;z-index:2;}',
      '[data-vp-tile-select] [data-vp-tile-check]{left:0;top:0;pointer-events:none;}',
      '[data-vp-tile-input]:not(:checked)+[data-vp-tile-check]{background:rgba(0,0,0,.34);border:1.5px solid rgba(255,255,255,.82);box-shadow:0 2px 8px rgba(0,0,0,.24);}',
      '[data-vp-tile-input]:not(:checked)+[data-vp-tile-check] svg{display:none;}',
      '[data-vp-tile-primary]{position:absolute;right:7px;top:7px;border-radius:6px;padding:3px 6px;background:var(--vp-accent);color:#fff;font-size:9.5px;line-height:1;font-weight:700;letter-spacing:.03em;box-shadow:0 2px 8px rgba(0,0,0,.24);z-index:3;}',
      '[data-vp-tile-title]{font-size:13px;line-height:1.35;font-weight:600;letter-spacing:-.01em;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}',
      '[data-vp-tile-meta]{display:flex;gap:8px;align-items:center;font-size:11px;color:#8a8781;overflow:hidden;white-space:nowrap;font-variant-numeric:tabular-nums;}',
      '[data-vp-tile-up]{max-width:112px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '[data-vp-tile-views]{margin-left:auto;color:#9a968d;}',
      '[data-vp-tile-views] + [data-vp-tile-views]{margin-left:0;}',
      '[data-vp-picker-cover]{width:100%;height:84px;border-radius:8px;object-fit:cover;background:rgba(128,128,128,.1);}',
      '[data-vp-picker-coverwrap]{position:relative;width:100%;height:84px;}',
      '[data-vp-picker-coverwrap]>[data-vp-picker-cover]{position:absolute;inset:0;width:100%;height:100%;}',
      '[data-vp-picker-cover][data-empty="on"]{display:flex;align-items:center;justify-content:center;font-size:20px;color:#9a968d;}',
      '[data-vp-picker-item-title]{font-size:11.5px;line-height:1.35;font-weight:600;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}',
      '[data-vp-picker-item-meta]{font-size:10.5px;color:#8a8781;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      // Auto-pick hold bar: the animation itself says "processing starts when this
      // fills". Hover pauses it (and tells the Host to pause too) so nobody has to
      // race a countdown; clicking takes over the choice.
      '[data-vp-hold-bar]{position:relative;height:7px;border-radius:999px;background:rgba(128,128,128,.16);margin:2px 0 10px;overflow:hidden;cursor:pointer;transition:height .14s ease,box-shadow .18s ease;}',
      '[data-vp-hold-bar]:hover{height:11px;box-shadow:0 0 0 1px var(--vp-accent-line),0 4px 12px rgba(0,0,0,.10);}',
      '[data-vp-hold-fill]{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:999px;background:linear-gradient(90deg,var(--vp-accent),var(--vp-accent-tint));animation-name:vp-hold-fill;animation-timing-function:linear;animation-fill-mode:forwards;}',
      '[data-vp-hold-bar]:hover [data-vp-hold-fill]{background:linear-gradient(90deg,var(--vp-accent-strong),var(--vp-accent));}',
      '[data-vp-hold="taken"] [data-vp-picker-title]{color:var(--dsw-alias-label-secondary,#4b4b47);}',
      '[data-vp-hold="taken"] [data-vp-hold-fill]{background:linear-gradient(90deg,#8a8781,#c0bcb2);animation-play-state:paused;}',
      '[data-vp-hold="done"] [data-vp-hold-fill]{background:linear-gradient(90deg,var(--vp-accent),var(--vp-accent-tint));}',
      '[data-vp-hold="taken"] [data-vp-picker-list] [data-vp-picker-item]{cursor:default;}',
      '[data-vp-hold-item] input{width:15px;height:15px;margin-right:2px;accent-color:var(--vp-accent);}',      '[data-vp-hold="taken"] [data-vp-hold-item]{border-color:var(--vp-accent-line);}',
      '[data-vp-auto-row]{display:flex;align-items:center;gap:8px;margin:2px 0 8px;padding:9px 10px;border:1px solid var(--vp-accent-line);border-radius:10px;background:var(--vp-accent-soft);font-size:12.5px;line-height:1.3;min-width:0;}',
      '[data-vp-auto-count]{flex:none;min-width:22px;text-align:center;font-size:20px;line-height:1;font-weight:700;font-variant-numeric:tabular-nums;color:var(--vp-accent);}',
      '[data-vp-auto-copy]{flex:none;color:var(--dsw-alias-label-secondary,#4b4b47);}',
      '[data-vp-auto-primary]{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;}',
      '[data-vp-auto-takeover]{flex:none;margin-left:auto;border:1px solid var(--vp-accent-line);border-radius:7px;background:transparent;color:var(--vp-accent);font:600 11.5px/1 inherit;padding:6px 9px;cursor:pointer;}',
      '[data-vp-auto-takeover]:hover{background:var(--vp-accent);color:var(--vp-on-accent,#08131f);}',
      '[data-vp-search-count]{flex:none;border-radius:999px;padding:2px 7px;font-size:11px;font-weight:650;background:var(--vp-accent-soft);color:var(--vp-accent);border:1px solid var(--vp-accent-line);}',
      '[data-vp-search-line]{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--dsw-alias-label-secondary,#4b4b47);min-width:0;}',
      '[data-vp-search-line]>span:last-child{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '[data-vp-search-list]{display:flex;flex-direction:column;gap:6px;margin-top:8px;}',
      '[data-vp-search-item]{display:flex;align-items:center;gap:9px;min-width:0;}',
      '[data-vp-search-cover]{width:72px;height:40px;border-radius:7px;object-fit:cover;background:linear-gradient(135deg,#2c2c2e,#545458);flex:none;}',
      '[data-vp-search-body]{min-width:0;flex:1;}',
      '[data-vp-search-name]{font-size:12px;font-weight:600;color:inherit;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '[data-vp-search-meta]{font-size:10.5px;color:var(--vp-muted,#63605a);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '[data-vp-search-dots]{display:inline-flex;align-items:center;gap:3px;flex:none;height:12px;}',
      '[data-vp-search-dots] i{width:4px;height:4px;border-radius:50%;background:var(--vp-accent);animation:vp-search-dot 1.15s ease-in-out infinite;}',
      '[data-vp-search-dots] i:nth-child(2){animation-delay:.15s;}',
      '[data-vp-search-dots] i:nth-child(3){animation-delay:.3s;}',
      '@keyframes vp-search-dot{0%,70%,100%{opacity:.25;transform:translateY(0)}35%{opacity:1;transform:translateY(-2px)}}',
      '@media (max-width:620px){[data-vp-picker-list][data-count="2"],[data-vp-picker-list][data-count="3"],[data-vp-picker-list][data-count="4"],[data-vp-picker-list][data-count="5"],[data-vp-picker-list][data-count="6"],[data-vp-picker-list][data-count="7"],[data-vp-picker-list][data-count="8"],[data-vp-picker-list][data-count="9"],[data-vp-picker-list][data-count="10"]{grid-template-columns:repeat(2,minmax(0,1fr));}[data-vp-picker-list][data-count="1"]{grid-template-columns:minmax(0,1fr);}}',
      '@keyframes vp-hold-fill{from{width:0}to{width:100%}}',
      '[data-vp-hold-actions]{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:10px;}',
      '[data-vp-hold-start]{border:0;border-radius:10px;background:var(--vp-accent);color:#08131f;font:600 12.5px/1 inherit;padding:10px 14px;cursor:pointer;}',
      '[data-vp-hold-start]:hover{background:var(--vp-accent-strong);}',
      '[data-vp-hold-start]:disabled{opacity:.55;cursor:default;}',
      '[data-vp-hold-cancel]{border:1px solid rgba(128,128,128,.22);background:transparent;color:inherit;border-radius:10px;padding:9px 12px;font:12px/1 inherit;cursor:pointer;}',
      '[data-vp-hold-error]{color:#c0392b;font-size:11.5px;}',
      '[data-vp-hold-warning]{margin:2px 0 8px;color:#9a6700;background:rgba(255,204,0,.10);border:1px solid rgba(255,204,0,.25);border-radius:8px;padding:5px 8px;font-size:11px;line-height:1.4;}',
      '@keyframes vp-pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.82)}}',
      // User requirement: the only Video2Agent card is the one above the composer.
      // Never render the plugin's tool-result cards in the chat transcript.
      '[data-vp-card]{display:none!important;}',
      '[data-ds-theme-source="dark"] [data-vp-card],[data-ds-theme="dark"] [data-vp-card]{--vp-glass-bg:linear-gradient(180deg,rgba(30,31,33,.94),rgba(30,31,33,.86));--vp-glass-line:rgba(255,255,255,.10);background:var(--vp-glass-bg);border-color:var(--vp-glass-line);color:#f2f0e9;}[data-ds-theme-source="dark"] [data-vp-live],[data-ds-theme="dark"] [data-vp-live],[data-ds-theme-source="dark"] [data-vp-preview],[data-ds-theme="dark"] [data-vp-preview],[data-ds-theme-source="dark"] [data-vp-queue],[data-ds-theme="dark"] [data-vp-queue]{--vp-glass-bg:linear-gradient(180deg,rgba(30,31,33,.94),rgba(30,31,33,.86));--vp-glass-line:rgba(255,255,255,.10);background:var(--vp-glass-bg);border-color:var(--vp-glass-line);color:#f2f0e9;}[data-ds-theme-source="dark"] [data-vp-live-title],[data-ds-theme="dark"] [data-vp-live-title],[data-ds-theme-source="dark"] [data-vp-live-focus],[data-ds-theme="dark"] [data-vp-live-focus]{color:#f2f0e9;}[data-ds-theme-source="dark"] [data-vp-live-focus]{border-top-color:rgba(255,255,255,.12);}[data-ds-theme-source="dark"] [data-vp-picker],[data-ds-theme="dark"] [data-vp-picker],[data-ds-theme-source="dark"] [data-vp-search],[data-ds-theme="dark"] [data-vp-search]{background:#1f1f1b;border-color:rgba(255,255,255,.14);color:#f2f0e9;}[data-ds-theme-source="dark"] [data-vp-tile-title],[data-ds-theme="dark"] [data-vp-tile-title]{color:#f2f0e9;}[data-ds-theme-source="dark"] [data-vp-muted],[data-ds-theme="dark"] [data-vp-muted],[data-ds-theme-source="dark"] [data-vp-settings-note],[data-ds-theme="dark"] [data-vp-settings-note]{color:#b9b5aa;}[data-ds-theme-source="dark"]{--vp-muted:#b9b5aa;}@media (prefers-color-scheme:dark){[data-vp-card]{background:#1f1f1b;}[data-vp-chip]{color:var(--vp-accent-tint);background:var(--vp-accent-soft);}[data-vp-btn="primary"]{background:var(--vp-accent);border-color:var(--vp-accent);color:#141815;}[data-vp-preview],[data-vp-live],[data-vp-queue]{--vp-glass-bg:linear-gradient(180deg,rgba(30,31,33,.92),rgba(30,31,33,.84));--vp-glass-line:rgba(255,255,255,.10);background:var(--vp-glass-bg);border-color:var(--vp-glass-line);}[data-vp-step="active"]{background:var(--vp-accent-soft);border-color:var(--vp-accent-line);}}',
    ].join('')

    function parseCall(block) {
      try {
        const raw = block && block.call && block.call.argsRaw
        if (!raw) return null
        return JSON.parse(raw)
      } catch { return null }
    }

    function resultText(block) {
      if (!block || !Array.isArray(block.content)) return ''
      return block.content.filter((b) => b && b.type === 'text' && typeof b.text === 'string').map((b) => b.text).join('\n')
    }

    function parseJson(text) {
      const start = text.indexOf('{')
      const end = text.lastIndexOf('}')
      if (start < 0 || end <= start) return null
      try { return JSON.parse(text.slice(start, end + 1)) } catch { return null }
    }

    function field(row, key, fallback) {
      return row && row[key] !== undefined && row[key] !== null ? row[key] : fallback
    }

    // A local file's `source` is an absolute path; never show it as the title or
    // send it to the cover proxy. Only the last path segment is user-facing.
    function sourceName(source) {
      const text = String(source || '').split(/[?#]/)[0]
      const name = text.split(/[\\/]/).pop() || ''
      try { return decodeURIComponent(name) } catch { return name }
    }

    function fmtTime(ms) {
      if (!ms && ms !== 0) return ''
      const total = Math.max(0, Math.round(Number(ms)))
      const h = Math.floor(total / 3600000)
      const m = Math.floor((total % 3600000) / 60000)
      const s = Math.floor((total % 60000) / 1000)
      if (h) return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0')
      return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0')
    }

    function fmtViews(value) {
      const n = Number(value)
      if (!Number.isFinite(n) || n <= 0) return ''
      if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
      if (n >= 10000) return (n / 10000).toFixed(1) + '万'
      return String(Math.round(n))
    }

    function metaLine(job) {
      if (!job) return ''
      const parts = []
      if (job.uploader) parts.push(String(job.uploader))
      const views = fmtViews(job.views)
      if (views) parts.push(views + '播放')
      return parts.join(' · ')
    }

    function fmtClock(ms) {
      const total = Math.max(0, Math.round(Number(ms) / 1000))
      const m = Math.floor(total / 60)
      const s = total % 60
      return m + ':' + String(s).padStart(2, '0')
    }

    // Tool payloads carry millisecond timecodes ("00:02:56.720"). A live card is
    // read at a glance and the milliseconds only add noise, so trim them — the
    // exact value stays in the evidence payload.
    function shortTimecode(text) {
      return String(text == null ? '' : text).replace(/(\d{1,2}:\d{2}:\d{2})\.\d+/, '$1')
    }

    function copyText(text) {
      if (navigator.clipboard) navigator.clipboard.writeText(String(text || ''))
    }

    const RESOLVE_CACHE = new Map()
    const RESOLVE_CACHE_TS = new Map()
    const RESOLVE_CACHE_KEY = 'video2agent.resolve.cache.v1'
    // A resolve survives a page refresh, not just the current mount. Keep the
    // payload small and bounded (24 entries); the settings TTL still decides
    // whether a persisted entry is fresh enough to use.
    // Resolve answers with the canonical URL (trailing slash, sometimes ?p=1)
    // while an ingest source may omit it. Comparing raw strings dropped the
    // title/cover and left the direct row as a bare "视频".
    function resolveUrlKey(value) {
      const raw = String(value == null ? '' : value).trim()
      if (!raw) return ''
      try {
        const u = new URL(raw)
        u.hash = ''
        const pathname = u.pathname.replace(/\/+$/, '')
        // Only scheme/host are case-insensitive: a Bilibili BV id is mixed case,
        // and two ids that differ only by case are different videos.
        return u.protocol.toLowerCase() + '//' + u.host.toLowerCase() + pathname + u.search
      } catch {
        return raw.replace(/\/+$/, '')
      }
    }
    try {
      const saved = JSON.parse(localStorage.getItem(RESOLVE_CACHE_KEY) || '[]')
      if (Array.isArray(saved)) {
        for (const item of saved.slice(0, 24)) {
          if (item && item.url && item.data && Number(item.at)) {
            RESOLVE_CACHE.set(String(item.url), item.data)
            RESOLVE_CACHE_TS.set(String(item.url), Number(item.at))
          }
        }
      }
    } catch {}
    function persistResolveCache() {
      try {
        const rows = [...RESOLVE_CACHE.entries()].map(([url, data]) => ({ url, data, at: RESOLVE_CACHE_TS.get(url) || 0 }))
        localStorage.setItem(RESOLVE_CACHE_KEY, JSON.stringify(rows))
      } catch {}
    }
    const SETTINGS_KEY = 'video2agent.settings.v1'
    const SETTINGS_URL = '/api/video2agent/settings'
    const CARD_HOLD_MS = 8000
    // A failed cover request must not leave an empty white box that collapses
    // the row. This inline placeholder is a play glyph on a neutral surface.
    const COVER_FALLBACK = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="96" height="54"><rect width="96" height="54" fill="#2c2c2e"/><path d="M38 17v20l18-10z" fill="#8b8172"/></svg>')
    const DEFAULT_SETTINGS = { enabled: true, cacheTtlMs: 24 * 60 * 60 * 1000, cacheExpire: true, cacheDays: 7, cacheLimitEnabled: false, cacheLimitGb: 20, accentColor: '#0a84ff', processLimit: 10 }
    const SETTINGS_LISTENERS = new Set()
    let SETTINGS = null

    // The accent is a user setting, not a hard-coded palette. One base hex
    // expands into the five tokens the cards consume, written to a single style
    // element, so chat cards, the composer preview, the live strip and the
    // settings page all follow the same colour at once.
    const ACCENT_PRESETS = [
      { label: 'DSH 蓝', value: '#0a84ff' },
      { label: '石墨灰', value: '#5b6472' },
      { label: '靛紫', value: '#6b5cff' },
      { label: '深蓝', value: '#2563eb' },
      { label: '琥珀', value: '#d97706' },
    ]
    const ACCENT_FALLBACK = '#0a84ff'

    function accentHex(value) {
      const text = String(value == null ? '' : value).trim()
      return /^#[0-9a-f]{6}$/i.test(text) ? text.toLowerCase() : ACCENT_FALLBACK
    }

    function accentRgb(hex) {
      const n = parseInt(accentHex(hex).slice(1), 16)
      return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
    }

    function accentMix(hex, target, amount) {
      const c = accentRgb(hex)
      const blend = (a, b) => Math.max(0, Math.min(255, Math.round(a + (b - a) * amount)))
      const two = (v) => v.toString(16).padStart(2, '0')
      return '#' + two(blend(c.r, target.r)) + two(blend(c.g, target.g)) + two(blend(c.b, target.b))
    }

    function accentPalette(value) {
      const base = accentHex(value)
      const { r, g, b } = accentRgb(base)
      return {
        accent: base,
        strong: accentMix(base, { r: 0, g: 0, b: 0 }, 0.22),
        tint: accentMix(base, { r: 255, g: 255, b: 255 }, 0.34),
        soft: 'rgba(' + r + ',' + g + ',' + b + ',.10)',
        line: 'rgba(' + r + ',' + g + ',' + b + ',.22)',
      }
    }

    function accentCss(value) {
      const p = accentPalette(value)
      return '[data-vp-card],[data-vp-preview],[data-vp-live],[data-vp-settings],[data-vp-picker],[data-vp-search],[data-vp-queue]{'
        + '--vp-accent:' + p.accent + ';'
        + '--vp-accent-strong:' + p.strong + ';'
        + '--vp-accent-tint:' + p.tint + ';'
        + '--vp-accent-soft:' + p.soft + ';'
        + '--vp-accent-line:' + p.line + ';}'
    }

    function applyAccentTheme(value) {
      if (typeof document === 'undefined') return
      try {
        let el = typeof document.querySelector === 'function' ? document.querySelector('style[data-vp-theme]') : null
        if (!el) {
          if (typeof document.createElement !== 'function' || !document.head || typeof document.head.appendChild !== 'function') return
          el = document.createElement('style')
          if (typeof el.setAttribute === 'function') el.setAttribute('data-vp-theme', '')
          document.head.appendChild(el)
        }
        el.textContent = accentCss(value)
      } catch {}
    }

    SETTINGS_LISTENERS.add((next) => applyAccentTheme(next && next.accentColor))

    function getSettings() {
      if (SETTINGS) return SETTINGS
      try {
        const raw = typeof window !== 'undefined' && window.localStorage ? window.localStorage.getItem(SETTINGS_KEY) : null
        SETTINGS = raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : { ...DEFAULT_SETTINGS }
      } catch { SETTINGS = { ...DEFAULT_SETTINGS } }
      return SETTINGS
    }

    // Saves are serialized: two rapid toggles used to race, and the later
    // response (merged settings) rolled back the other field. One chain keeps
    // the order the user clicked in.
    let SETTINGS_SAVE_CHAIN = Promise.resolve()
    // The last value the server actually acknowledged. Diffing against the
    // optimistic SETTINGS made a failed key invisible: the next save compared
    // against its own failed value and never re-sent it.
    let SETTINGS_ACKED = null
    // ui-settings.json exists but is unparseable: reads fail, but a write
    // replaces the file, so saving must stay possible.
    let SETTINGS_CORRUPT = false

    async function saveSettings(next, sync = true) {
      // Merge over the current settings for the local UI, but POST only the keys
      // that actually changed. Posting the merged SETTINGS froze every Config
      // key into ui-settings.json on the first save.
      const before = { ...(SETTINGS_ACKED || SETTINGS || {}) }
      SETTINGS = { ...DEFAULT_SETTINGS, ...(SETTINGS || {}), ...(next || {}) }
      const patch = {}
      for (const [key, value] of Object.entries(next || {})) {
        if (JSON.stringify(before[key]) !== JSON.stringify(value)) patch[key] = value
      }
      try {
        if (typeof window !== 'undefined' && window.localStorage) window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(SETTINGS))
      } catch {}
      for (const fn of SETTINGS_LISTENERS) fn(SETTINGS)
      if (!sync) return true
      if (!Object.keys(patch).length) return true
      const task = SETTINGS_SAVE_CHAIN.then(async () => {
      try {
        const response = await fetch(SETTINGS_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        })
        if (!response.ok) return false
        // The Host returns the merged settings. Applying that response is what
        // keeps a cache-limit change from resetting an unrelated field.
        let saved = null
        try { saved = await response.json() } catch {}
        if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
          SETTINGS = { ...DEFAULT_SETTINGS, ...saved }
          SETTINGS_ACKED = { ...SETTINGS }
          try {
            if (typeof window !== 'undefined' && window.localStorage) window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(SETTINGS))
          } catch {}
          for (const fn of SETTINGS_LISTENERS) fn(SETTINGS)
        }
        return true
      } catch { return false }
      })
      SETTINGS_SAVE_CHAIN = task.catch(() => {})
      return task
    }

    // Why the settings panel may be showing defaults: the read failed. Without this
    // flag the page rendered DEFAULT_SETTINGS as if they were the saved ones.
    let SETTINGS_STATE = 'loading'
    const SETTINGS_STATE_LISTENERS = new Set()
    // Settings is a tab in DSH. Without this cache every remount painted the
    // defaults (local ASR / unconfigured cloud / 未登录) until three fetches
    // resolved, which looked like the config had been lost and then restored.
    const SETTINGS_CACHE_KEY = 'video2agent.settings.cache.v1'
    function loadSettingsCache() {
      try { return JSON.parse(localStorage.getItem(SETTINGS_CACHE_KEY) || '{}') || {} } catch { return {} }
    }
    const SETTINGS_CACHE = loadSettingsCache()
    let CLOUD_CACHE = SETTINGS_CACHE.cloud || null
    let CLOUD_DRAFT_CACHE = SETTINGS_CACHE.cloudDraft || null
    let MODELS_CACHE = SETTINGS_CACHE.models || null
    let BILI_CACHE = SETTINGS_CACHE.bili || null
    function persistSettingsCache(patch) {
      Object.assign(SETTINGS_CACHE, patch)
      try { localStorage.setItem(SETTINGS_CACHE_KEY, JSON.stringify(SETTINGS_CACHE)) } catch {}
    }
    async function prefetchSettingsCache() {
      const base = '/api/video2agent'
      try {
        const [cloudRes, modelRes, biliRes] = await Promise.all([
          fetch(base + '/cloud'), fetch(base + '/models'), fetch(base + '/bili-login/status'),
        ])
        const [cloud, models, bili] = await Promise.all([
          cloudRes.json().catch(() => null), modelRes.json().catch(() => null), biliRes.json().catch(() => null),
        ])
        if (cloud && cloud.ok !== false) {
          CLOUD_CACHE = { ...cloud, state: 'ready' }
          CLOUD_DRAFT_CACHE = {
            provider: cloud.provider || 'siliconflow',
            base_url: cloud.base_url || 'https://api.siliconflow.cn/v1',
            asr_model: cloud.asr_model || '',
            ocr_model: cloud.ocr_model || '',
            asr_enabled: cloud.asr_enabled !== false,
          }
          persistSettingsCache({ cloud: CLOUD_CACHE, cloudDraft: CLOUD_DRAFT_CACHE })
        }
        if (models && models.ok !== false) {
          MODELS_CACHE = { ...models, state: 'ready' }
          persistSettingsCache({ models: MODELS_CACHE })
        }
        if (bili && bili.ok !== false) {
          BILI_CACHE = { loggedIn: !!bili.logged_in, uid: bili.uid || '', state: 'ready' }
          persistSettingsCache({ bili: BILI_CACHE })
        }
      } catch {}
    }
    if (typeof window !== 'undefined') window.__video2agentPrefetchSettings = prefetchSettingsCache
    function setSettingsState(next) {
      SETTINGS_STATE = next
      for (const fn of SETTINGS_STATE_LISTENERS) fn(next)
    }

    async function hydrateSettings() {
      try {
        const response = await fetch(SETTINGS_URL)
        if (!response.ok) {
          // A corrupt file can still be repaired by the next save: the Host
          // merges the patch into a fresh object and rewrites it.
          let code = ''
          try {
            const body = await response.json()
            code = String((body && body.code) || '')
          } catch {}
          SETTINGS_CORRUPT = code === 'E_SETTINGS_CORRUPT'
          setSettingsState('error')
          return
        }
        const remote = await response.json()
        if (!remote || typeof remote !== 'object') { setSettingsState('error'); return }
        SETTINGS = { ...DEFAULT_SETTINGS, ...remote }
        SETTINGS_ACKED = { ...SETTINGS }
        try {
          if (typeof window !== 'undefined' && window.localStorage) window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(SETTINGS))
        } catch {}
        for (const fn of SETTINGS_LISTENERS) fn(SETTINGS)
        SETTINGS_CORRUPT = false
        setSettingsState('ready')
        // Do not fire three model/bili/settings GETs at module load when the
        // plugin is disabled or the page never opens its settings.
        if (SETTINGS.enabled && typeof fetch === 'function') prefetchSettingsCache()
      } catch { setSettingsState('error') }
    }

    function useSettingsState() {
      const [value, setValue] = React.useState(SETTINGS_STATE)
      React.useEffect(() => {
        SETTINGS_STATE_LISTENERS.add(setValue)
        setValue(SETTINGS_STATE)
        return () => SETTINGS_STATE_LISTENERS.delete(setValue)
      }, [])
      return value
    }

    function useSettings() {
      const [value, setValue] = React.useState(getSettings())
      React.useEffect(() => {
        SETTINGS_LISTENERS.add(setValue)
        setValue(getSettings())
        return () => SETTINGS_LISTENERS.delete(setValue)
      }, [])
      return value
    }

    const LIVE_LISTENERS = new Set()
    // One live entry per conversation. A single module-global used to be shared
    // by every session, so a card belonging to another conversation could
    // replace (or be re-labelled into) the active one. Entries are keyed by the
    // session id the publisher declares; LIVE_ANY holds publishes that happen
    // before any session is known (plain debug hook / very first paint).
    const LIVE_BY_SESSION = new Map()
    let LIVE_ANY = null
    let ACTIVE_SESSION = null

    function liveFor(sessionId) {
      if (!sessionId) return LIVE_ANY
      let entry = LIVE_BY_SESSION.get(sessionId) || null
      // A status published before any conversation was known (first paint, or
      // the debug hook) is adopted by the first session that renders, instead
      // of being stranded forever or shown to every later session.
      if (!entry && LIVE_ANY) {
        entry = LIVE_ANY
        LIVE_BY_SESSION.set(sessionId, entry)
        LIVE_ANY = null
      }
      return entry
    }

    function storeLive(sessionId, value) {
      if (sessionId) LIVE_BY_SESSION.set(sessionId, value)
      else LIVE_ANY = value
      for (const fn of LIVE_LISTENERS) fn(value)
    }

    // A shortlist can start more than one job. LiveStrip can only show one active
    // job, so the rest need their own visible queue instead of disappearing.
    const QUEUE_LISTENERS = new Set()
    const QUEUE_BY_SESSION = new Map()
    // The last evidence moment per conversation, used by the batch summary. It is
    // deliberately text-only: the frame stays an attachment for the model, and the
    // user gets the timecode plus the line that was actually read.
    const LAST_EVIDENCE = new Map()
    const EVIDENCE_LISTENERS = new Set()
    const LAST_BATCH_LIVE = new Map()
    function recordEvidence(sessionId, note) {
      if (!sessionId) return
      if (note) LAST_EVIDENCE.set(sessionId, note)
      else LAST_EVIDENCE.delete(sessionId)
      // Persist with the queue: the completed table is the record, and a reload
      // must not turn a verified moment into "索引已就绪" again.
      const queue = queueFor(sessionId)
      if (queue) storeQueue(sessionId, { ...queue, evidence: note || null })
      for (const fn of EVIDENCE_LISTENERS) fn(sessionId)
    }
    function queueStorageKey(sessionId) { return 'video2agent.queue.' + String(sessionId || '') }
    function queueClearedKey(sessionId) { return 'video2agent.queue.cleared.' + String(sessionId || '') }
    // The latch stores { at, ids } so a replay of the *cleared* card is still
    // rejected while a genuinely new direct ingest (different job id) passes.
    // Older builds stored a bare timestamp; both shapes must parse.
    function queueClearedRecord(sessionId) {
      try {
        if (typeof localStorage === 'undefined') return { at: 0, ids: [] }
        const raw = localStorage.getItem(queueClearedKey(sessionId))
        if (!raw) return { at: 0, ids: [] }
        if (raw.charAt(0) === '{') {
          const parsed = JSON.parse(raw)
          return {
            at: Number(parsed && parsed.at) || 0,
            ids: Array.isArray(parsed && parsed.ids) ? parsed.ids.map(String) : [],
          }
        }
        return { at: Number(raw) || 0, ids: [] }
      } catch { return { at: 0, ids: [] } }
    }
    function queueClearedAt(sessionId) { return queueClearedRecord(sessionId).at }
    function markQueueCleared(sessionId, jobIds) {
      try {
        if (typeof localStorage === 'undefined') return
        localStorage.setItem(queueClearedKey(sessionId), JSON.stringify({
          at: Date.now(),
          ids: Array.from(new Set((jobIds || []).map(String).filter(Boolean))).slice(0, 200),
        }))
      } catch {}
    }
    function queueFor(sessionId) {
      if (!sessionId) return null
      if (QUEUE_BY_SESSION.has(sessionId)) return QUEUE_BY_SESSION.get(sessionId) || null
      try {
        const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(queueStorageKey(sessionId)) : null
        const parsed = raw ? JSON.parse(raw) : null
        if (parsed && Array.isArray(parsed.jobs) && parsed.jobs.length) {
          QUEUE_BY_SESSION.set(sessionId, parsed)
          return parsed
        }
      } catch {}
      return null
    }
    function storeQueue(sessionId, value) {
      if (!sessionId) return
      if (value) QUEUE_BY_SESSION.set(sessionId, value)
      else QUEUE_BY_SESSION.delete(sessionId)
      try {
        if (typeof localStorage !== 'undefined') {
          if (value) {
            localStorage.setItem(queueStorageKey(sessionId), JSON.stringify(value))
            // A new batch invalidates the old "user cleared this" latch.
            localStorage.removeItem(queueClearedKey(sessionId))
          } else {
            localStorage.removeItem(queueStorageKey(sessionId))
            // Remember the clear time so a historical ingest/job card cannot
            // recreate this queue when the conversation is reopened.
            localStorage.setItem(queueClearedKey(sessionId), String(Date.now()))
          }
        }
      } catch {}
      for (const fn of QUEUE_LISTENERS) fn(value)
    }

    // Clearing the batch is one action: the receipt goes, the table goes, and the
    // single-job card published for the batch's last row must not take the table's
    // place. Observed: the user clicks 清除 on a completed table, and the same
    // completion immediately reappears as a LiveStrip card for the rest of its 8s
    // hold. Hiding the live entry here also covers the auto-clear at 8s.
    function clearBatch(sessionId) {
      if (!sessionId) return
      const queue = queueFor(sessionId)
      const live = liveFor(sessionId)
      const jobIds = new Set((queue && Array.isArray(queue.jobs) ? queue.jobs : [])
        .map((job) => String((job && job.job_id) || '')))
      // Only hide a card this batch owns: a different job that is still running
      // keeps its card.
      const owned = !live || !live.jobId || live.phase !== 'running' || jobIds.has(String(live.jobId))
      recordEvidence(sessionId, null)
      if (live && owned && live.hidden !== true) {
        publishLive({ sessionId, hidden: true, hiddenAt: Date.now() })
      }
      storeQueue(sessionId, null)
      markQueueCleared(sessionId, [...jobIds])
    }

    function publishLive(next) {
      const payload = next || {}
      const explicitSession = payload.sessionId ? String(payload.sessionId) : null
      // An explicit owner always wins: a publisher that knows its session must
      // never be re-labelled into whichever session happens to be active. A
      // publisher that declares nothing still targets the active conversation,
      // which is the pre-refactor behaviour for the debug hook and legacy calls.
      const targetSession = explicitSession || ACTIVE_SESSION || null
      const current = liveFor(targetSession)
      const merged = { ...(current || {}) }
      const hiddenAt = Number(merged.hiddenAt || 0)
      const createdMs = payload.createdAt ? Date.parse(payload.createdAt) : 0
      const newerThanHidden = !!(createdMs && createdMs > hiddenAt)
      if (payload.phase === 'running' && (!merged.hidden || newerThanHidden)) {
        merged.hidden = false
        delete merged.hiddenKey
        delete merged.hiddenAt
      }
      if (payload.hidden) {
        // A watchdog hides the job it was watching; it must never hide a newer
        // card that replaced that job in the same session.
        if (payload.jobId && current && current.jobId
            && String(current.jobId) !== String(payload.jobId)) return
        merged.hiddenAt = payload.hiddenAt || Date.now()
        merged.hiddenKey = payload.hiddenKey || merged.jobId || merged.videoId
      }
      const incomingJob = payload.jobId
      const sameJob = !!(incomingJob && current && current.jobId === incomingJob)
      const sameVideo = !!(payload.videoId && !incomingJob && current && current.videoId === payload.videoId)
      // The turn ended and the card is already wrapping up. Its own JobCard can
      // still deliver one more poll (setJob -> publish) before it unmounts; that
      // used to flip 本轮结束 back to 正在处理, cancel the 3s exit timer and keep
      // the card on screen until the job itself finished. A closing card accepts
      // only a genuinely new job (different id, or a newer createdAt).
      const closingCurrent = !!(current && current.phase === 'closing' && current.closing === true)
      const incomingCreated = payload.createdAt ? Date.parse(payload.createdAt) : 0
      const reopened = !!(incomingCreated && incomingCreated > Number(current && current.closedAt || 0))
      if (closingCurrent && sameJob && !reopened
          && (payload.phase === 'running' || payload.phase === 'ready' || payload.phase === 'error')) {
        return
      }
      // One owner per session. A batch may take over a running direct card (the
      // user just started a batch); a direct ingest may not steal the card from a
      // running batch, and two polls for different jobs must not alternate.
      if (incomingJob && current && current.jobId && incomingJob !== current.jobId
          && current.phase === 'running' && current.hidden !== true) {
        // A batch may take over a running direct card; a direct ingest may not
        // steal the card from a running batch (or from another direct job).
        const incomingOwner = payload.origin || ''
        if (incomingOwner === 'direct' && current.origin) return
      }
      if (payload.origin) merged.origin = payload.origin
      if (incomingJob && current && current.jobId && incomingJob !== current.jobId) {
        delete merged.title
        delete merged.coverUrl
        delete merged.duration
        delete merged.videoId
        delete merged.focusLabel
        delete merged.focusNote
      }
      if (payload.clearFocus) { delete merged.focusLabel; delete merged.focusNote }
      for (const [key, value] of Object.entries(payload)) {
        if (key === 'clearFocus') continue
        if (value !== undefined && value !== null && value !== '') merged[key] = value
      }
      if (explicitSession) merged.sessionId = explicitSession
      else if ((sameJob || sameVideo) && current && current.sessionId) merged.sessionId = current.sessionId
      else if (ACTIVE_SESSION) merged.sessionId = ACTIVE_SESSION
      // canceled/cancelled are terminal too: treating them as running kept a
      // canceled card on screen and let the watchdog revive it forever.
      const terminalPhase = payload.phase === 'ready' || payload.phase === 'error'
        || payload.phase === 'canceled' || payload.phase === 'cancelled'
      const terminalPhases = ['ready', 'error', 'canceled', 'cancelled']
      const incomingKey = String(payload.jobId || payload.videoId || '')
      const currentKey = current ? String(current.jobId || current.videoId || '') : ''
      const sameTerminalJob = !!(terminalPhase && current
        && terminalPhases.includes(current.phase)
        && current.phase === payload.phase
        && incomingKey && incomingKey === currentKey)
      if (payload.phase === 'running') delete merged.finishedAt
      if (terminalPhase && !sameTerminalJob) merged.finishedAt = Date.now()
      if (sameTerminalJob) {
        if (current.updatedAt) merged.updatedAt = current.updatedAt
      } else {
        merged.updatedAt = Date.now()
      }
      if (current && JSON.stringify(merged) === JSON.stringify(current)) return
      // Keep the in-memory map bounded; a conversation that disappears from the
      // UI does not need its transient progress forever.
      if (explicitSession && LIVE_BY_SESSION.size > 24) {
        const oldest = LIVE_BY_SESSION.keys().next().value
        if (oldest && oldest !== explicitSession && oldest !== ACTIVE_SESSION) LIVE_BY_SESSION.delete(oldest)
      }
      storeLive(targetSession, merged)
    }

    function publishSession(sid) {
      const live = liveFor(sid)
      if (!live) return
      const merged = { ...live, currentSession: sid }
      if (JSON.stringify(merged) === JSON.stringify(live)) return
      storeLive(sid, merged)
    }

    // The strip itself never polls; it only renders whatever the JobCard pushed
    // into it. When the card stops pushing (the turn ends and the card unmounts,
    // or the page is re-rendered) a running entry stayed on screen forever — the
    // "task finished but the plugin is still hanging there" bug. This watchdog
    // is the strip's own safety net: only entries that have not been refreshed
    // for JOB_STALE_MS are re-checked, so it never duplicates a live card's poll.
    const JOB_STALE_MS = 5000
    const WATCHDOG_MS = 2000
    const WATCHDOG_FAIL_LIMIT = 5
    let WATCHDOG_TIMER = null
    let WATCHDOG_BUSY = false
    const WATCHDOG_FAILS = new Map()
    let WATCHDOG_VISIBILITY = null
    let WATCHDOG_FOCUS = null

    function closeLive(sessionId, entry) {
      if (!entry || entry.hidden === true) return
      if (entry.phase !== 'running') return
      // The batch table owns the surface whenever it has a row. Publishing a
      // turn-end card on top of it (or just after it clears) duplicated the same
      // completion: 本轮结束 went away and the 已完成 table appeared behind it.
      if (sessionId && queueFor(sessionId)) return
      // The turn ended, so the card ends with it: freeze the ring, say how it
      // ended, then take the normal fade. The in-chat JobCard stays as the record
      // and the job itself keeps running in the background.
      const done = Number(entry.pct || 0) >= 100
      publishLive({
        sessionId: sessionId || undefined,
        phase: 'closing',
        closing: true,
        closedAt: Date.now(),
        stage: done ? '已完成' : '本轮结束',
        etaMs: 0,
      })
    }

    // Sessions whose agent turn has been seen running. A close is only allowed on
    // a true -> false transition we actually observed, so mounting an idle
    // session does not kill a background card.
    const SESSION_WAS_RUNNING = new Set()

    function watchdogEntries() {
      const entries = [...LIVE_BY_SESSION.entries()]
      if (LIVE_ANY) entries.push([null, LIVE_ANY])
      return entries
    }

    async function watchdogTick() {
      if (typeof fetch !== 'function') return
      if (WATCHDOG_BUSY) return
      WATCHDOG_BUSY = true
      try {
        await Promise.all(watchdogEntries().map(async ([sessionId, entry]) => {
          if (!entry || entry.phase !== 'running' || !entry.jobId) return
          if (entry.hidden === true) return
          if (Date.now() - Number(entry.updatedAt || 0) < JOB_STALE_MS) return
          const key = String(sessionId || '-') + '|' + entry.jobId
          try {
            // overview=0 keeps the 2s watchdog from spawning an overview CLI;
            // the job sidecar already has the stage/progress it needs.
            const response = await fetch('/api/video2agent/job?id=' + encodeURIComponent(entry.jobId) + '&overview=0')
            if (response.status === 404) {
              // The job is gone; a progress card for it is a lie.
              WATCHDOG_FAILS.delete(key)
              publishLive({ sessionId: sessionId || undefined, jobId: entry.jobId, hidden: true, hiddenAt: Date.now() })
              return
            }
            if (!response.ok) throw new Error('http ' + response.status)
            const data = await response.json()
            const job = normalizeJob(data)
            if (!job) throw new Error('no job in response')
            WATCHDOG_FAILS.delete(key)
            const pct = job.progress === null ? (job.state === 'ready' ? 100 : 0) : Math.round(Math.max(0, Math.min(1, job.progress)) * 100)
            // canceled is terminal: mapping it to running kept the card alive forever.
            const phase = job.state === 'failed' ? 'error'
              : (job.state === 'ready' || job.state === 'done') ? 'ready'
                : (job.state === 'canceled' || job.state === 'cancelled') ? 'canceled'
                  : 'running'
            const overview = data.overview
            publishLive({
              sessionId: sessionId || undefined,
              jobId: job.id,
              createdAt: job.createdAt,
              warningCount: overview && Array.isArray(overview.warnings) ? overview.warnings.length : 0,
              transcript: overview && overview.metrics ? overview.metrics.transcript_source : undefined,
              transcriptAvailable: overview && overview.capabilities ? overview.capabilities.transcript : undefined,
              captionKind: overview && overview.metrics && overview.metrics.caption_track ? overview.metrics.caption_track.kind : undefined,
              pct,
              etaMs: estimateEtaMs(job, pct, phase) || 0,
              durationMs: job.durationMs,
              positionMs: job.positionMs,
              stage: phase === 'error' ? '遇到问题' : friendlyStage(job.stage),
              phase,
              errorMessage: phase === 'error' ? (job.errorMessage || job.errorCode || '视频处理失败') : undefined,
              remedy: phase === 'error' ? job.remedy || undefined : undefined,
              focusLabel: phase === 'running' && Number(job.positionMs) > 0 ? fmtTime(job.positionMs) : undefined,
              focusNote: phase === 'running' && Number(job.positionMs) > 0 ? '当前画面' : undefined,
              clearFocus: true,
            })
          } catch {
            const fails = (WATCHDOG_FAILS.get(key) || 0) + 1
            WATCHDOG_FAILS.set(key, fails)
            if (fails >= WATCHDOG_FAIL_LIMIT) {
              // Unreachable for a while: drop the stale card rather than lie.
              WATCHDOG_FAILS.delete(key)
              publishLive({ sessionId: sessionId || undefined, jobId: entry.jobId, hidden: true, hiddenAt: Date.now() })
            }
          }
        }))
      } finally {
        WATCHDOG_BUSY = false
      }
    }

    function stopLiveWatchdog() {
      if (WATCHDOG_TIMER) { clearInterval(WATCHDOG_TIMER); WATCHDOG_TIMER = null }
      if (WATCHDOG_VISIBILITY && typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', WATCHDOG_VISIBILITY)
        WATCHDOG_VISIBILITY = null
      }
      if (WATCHDOG_FOCUS && typeof window !== 'undefined') {
        window.removeEventListener('focus', WATCHDOG_FOCUS)
        WATCHDOG_FOCUS = null
      }
    }

    function startLiveWatchdog() {
      if (WATCHDOG_TIMER || typeof setInterval !== 'function') return
      WATCHDOG_TIMER = setInterval(() => { watchdogTick().catch(() => {}) }, WATCHDOG_MS)
      // A backgrounded tab throttles timers, so a card can look stale for minutes
      // after the user comes back. Check immediately on return.
      if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
        WATCHDOG_VISIBILITY = () => {
          if (document.visibilityState === 'visible') watchdogTick().catch(() => {})
        }
        document.addEventListener('visibilitychange', WATCHDOG_VISIBILITY)
      }
      if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
        WATCHDOG_FOCUS = () => { watchdogTick().catch(() => {}) }
        window.addEventListener('focus', WATCHDOG_FOCUS)
      }
    }

    function useLive(sessionId) {
      const [, bump] = React.useState(0)
      React.useEffect(() => {
        const listener = () => bump((n) => n + 1)
        LIVE_LISTENERS.add(listener)
        return () => LIVE_LISTENERS.delete(listener)
      }, [])
      return liveFor(sessionId)
    }

    function useQueue(sessionId) {
      const [, bump] = React.useState(0)
      React.useEffect(() => {
        const listener = () => bump((n) => n + 1)
        QUEUE_LISTENERS.add(listener)
        return () => QUEUE_LISTENERS.delete(listener)
      }, [])
      return queueFor(sessionId)
    }

    function useEvidence(sessionId) {
      const [, bump] = React.useState(0)
      React.useEffect(() => {
        const listener = () => bump((n) => n + 1)
        EVIDENCE_LISTENERS.add(listener)
        return () => EVIDENCE_LISTENERS.delete(listener)
      }, [])
      const queue = queueFor(sessionId)
      return (queue && queue.evidence) || null
    }

    function sessionKey(props) {
      const s = props && props.session
      return (s && (s.id || s.sessionId)) || (props && (props.sessionId || props.session_id)) || null
    }

    function canPublishJob(sessionId, activeSession, live) {
      if (sessionId && activeSession && sessionId !== activeSession) return false
      if (sessionId && live && live.sessionId && live.sessionId !== sessionId) return false
      return true
    }

    // Accepted composer inputs: canonical BV links, av-number links, b23.tv short
    // links (resolved on the Host, which follows the redirect), and a bare BV id.
    // Anything else is left to the agent tool, which reports its own error.
    const B23_RE = /https?:\/\/b23\.tv\/[0-9A-Za-z]+/i
    const BILI_RE = /https?:\/\/(?:(?:www|m)\.)?bilibili\.com\/video\/(BV[0-9A-Za-z]{10}|av\d+)/i
    const BARE_BV_RE = /\bBV[0-9A-Za-z]{10}\b/

    function detectVideoLink(draft) {
      const text = String(draft || '')
      const short = text.match(B23_RE)
      if (short) return { url: short[0], form: 'short' }
      const full = text.match(BILI_RE)
      if (full) {
        return {
          url: 'https://www.bilibili.com/video/' + full[1],
          form: /^av/i.test(full[1]) ? 'av' : 'bv',
        }
      }
      const bare = text.match(BARE_BV_RE)
      if (bare) return { url: 'https://www.bilibili.com/video/' + bare[0], form: 'bare' }
      return null
    }

    function friendlyStage(stage) {
      const key = String(stage || '').toLowerCase()
      if (key.indexOf('transcrib') >= 0 || key.indexOf('asr') >= 0) return '正在听语音'
      if (key.indexOf('ocr') >= 0) return '正在读画面上的文字'
      if (key.indexOf('scene') >= 0 || key.indexOf('sampl') >= 0) return '正在找关键画面'
      if (key.indexOf('index') >= 0 || key.indexOf('visual') >= 0) return '正在整理内容'
      if (key.indexOf('download') >= 0 || key.indexOf('resolv') >= 0 || key.indexOf('prob') >= 0) return '正在准备视频'
      if (key.indexOf('done') >= 0 || key.indexOf('ready') >= 0) return '已完成'
      if (key.indexOf('fail') >= 0 || key.indexOf('error') >= 0 || key.indexOf('cancel') >= 0) return '遇到问题'
      return '正在分析视频'
    }

    const STAGES = [
      ['解析', ['resolving', 'probing']],
      ['转写', ['transcribing']],
      ['场景', ['scenes']],
      ['抽帧', ['sampling']],
      ['OCR', ['ocr']],
      ['索引', ['indexing', 'visual']],
    ]

    function stageIndex(stage) {
      const key = String(stage || '').toLowerCase()
      if (key === 'done') return STAGES.length
      for (let i = 0; i < STAGES.length; i++) if (STAGES[i][1].indexOf(key) >= 0) return i
      return -1
    }

    function sourceLabel(source) {
      if (source === 'asr') return '语音'
      if (source === 'caption') return '字幕'
      if (source === 'ocr_track' || source === 'ocr') return '画面文字'
      if (source === 'visual_segment') return '视觉结构'
      return source || ''
    }

    function estimateEtaMs(job, pct, phase) {
      if (phase !== 'running' || !job || pct < 10) return null
      const started = Date.parse(job.createdAt || '')
      if (!started) return null
      const elapsed = Date.now() - started
      if (elapsed < 10000) return null
      const eta = Math.round(elapsed * (100 - pct) / pct)
      if (!Number.isFinite(eta) || eta <= 0) return null
      return Math.min(eta, 2 * 60 * 60 * 1000)
    }

    function normalizeJob(data) {
      if (!data) return null
      const raw = data.job && data.job.id ? data.job : data
      const id = raw.job_id || raw.id
      if (!id) return null
      return {
        id: String(id),
        state: raw.state || 'running',
        stage: raw.stage || 'queued',
        progress: raw.progress === undefined || raw.progress === null ? null : Number(raw.progress),
        message: raw.message || '',
        videoId: raw.video_id || '',
        source: raw.source || '',
        createdAt: raw.created_at || '',
        durationMs: raw.duration_ms === undefined || raw.duration_ms === null ? null : Number(raw.duration_ms),
        positionMs: raw.position_ms === undefined || raw.position_ms === null ? null : Number(raw.position_ms),
        updatedAt: raw.updated_at || '',
        errorCode: raw.error_code || '',
        errorMessage: raw.error_message || '',
        remedy: raw.remedy || '',
      }
    }

    function JobSteps(props) {
      const active = stageIndex(props.stage)
      return h('div', { 'data-vp-steps': '' }, STAGES.map(([label], i) => {
        let state
        if (props.done) state = 'done'
        else if (i === active) state = 'active'
        else if (active >= 0 && i < active) state = 'done'
        return h('span', { key: label, 'data-vp-step': state }, label)
      }))
    }

    function JobCard(props) {
      const sessionId = props.sessionId || null
      const initial = normalizeJob(props.data)
      const [job, setJob] = React.useState(initial)
      const [overview, setOverview] = React.useState(props.overview || null)
      const [confirmed, setConfirmed] = React.useState(false)
      const [pollError, setPollError] = React.useState('')
      const [retryNonce, setRetryNonce] = React.useState(0)
      const jobId = job && job.id
      const running = !!job && (job.state === 'running' || job.state === 'queued')

      React.useEffect(() => {
        const next = normalizeJob(props.data)
        if (!next || (job && next.id === job.id)) return
        setJob(next)
        setOverview(props.overview || null)
        setConfirmed(false)
        setPollError('')
      }, [props.data, props.overview])

      React.useEffect(() => {
        if (!job || !confirmed) return
        const rawPct = job.progress === null ? (job.state === 'ready' ? 100 : 0) : Math.round(Math.max(0, Math.min(1, job.progress)) * 100)
        const phase = job.state === 'failed' ? 'error'
          : (job.state === 'ready' || job.state === 'done') ? 'ready'
            : (job.state === 'canceled' || job.state === 'cancelled') ? 'canceled'
              : 'running'
        const ownLive = liveFor(sessionId || ACTIVE_SESSION)
        if (!ownLive && phase !== 'running') return
        if (!ownLive && phase === 'running') {
          const created = Date.parse(job.createdAt || '')
          if (created && Date.now() - created > 10 * 60 * 1000) return
        }
        // A historical running JobCard must not publish into another session.
        if (!canPublishJob(sessionId, ACTIVE_SESSION, ownLive)) return
        const clock = String(job.message || '').match(/\b\d{1,2}:\d{2}(?::\d{2})?\b/)
        const clockLabel = clock && !/^0+:0+(?::0+)?$/.test(clock[0]) ? clock[0] : ''
        const positionMs = Number(job.positionMs)
        const positionLabel = Number.isFinite(positionMs) && positionMs > 0 ? fmtTime(positionMs) : clockLabel
        const durationLabel = job.durationMs ? fmtTime(job.durationMs) : ''
        // The ingest call's own URL is the only source available before the first
        // sidecar poll; without it a direct-link card starts with no cover.
        const liveSource = job.source || String(props.sourceHint || '')
        const cached = [...RESOLVE_CACHE.values()].find((d) => d && (
          (liveSource && resolveUrlKey(d.url) === resolveUrlKey(liveSource))
          || (job.videoId && String(d.video_id || '') === String(job.videoId))
        )) || null
        publishLive({
          sessionId: sessionId || undefined,
          origin: 'direct',
          title: (overview && overview.title) || (cached && cached.title) || undefined,
          warningCount: overview && Array.isArray(overview.warnings) ? overview.warnings.length : 0,
          transcript: overview && overview.metrics ? overview.metrics.transcript_source : undefined,
          transcriptAvailable: overview && overview.capabilities ? overview.capabilities.transcript : undefined,
          captionKind: overview && overview.metrics && overview.metrics.caption_track ? overview.metrics.caption_track.kind : undefined,
          duration: (overview && overview.duration) || (cached && cached.duration) || durationLabel || undefined,
          durationMs: job.durationMs,
          positionMs: job.positionMs,
          videoId: job.videoId,
          coverUrl: (overview && overview.cover_url) || (cached && cached.cover_url) || undefined,
          jobId: job.id,
          createdAt: job.createdAt,
          pct: rawPct,
          etaMs: estimateEtaMs(job, rawPct, phase) || 0,
          stage: phase === 'error' ? '遇到问题' : friendlyStage(job.stage),
          phase,
          errorMessage: phase === 'error' ? (job.errorMessage || job.errorCode || '视频处理失败') : undefined,
          remedy: phase === 'error' ? job.remedy || undefined : undefined,
          focusLabel: phase === 'running' && positionLabel ? positionLabel : undefined,
          focusNote: phase === 'running' && positionLabel ? '当前画面' : undefined,
          clearFocus: true
        })
      }, [job, overview, confirmed, sessionId])

      // A direct ingest must also produce the selected-video table. This is
      // deliberately not a picker: one row per job, status only.
      React.useEffect(() => {
        // Only an ingest result creates a direct-link row. A `jobs --wait` result
        // also looks like a job, but the shortlist table already owns that row; if
        // this effect ran for it, the row would lose the candidate title/uploader/
        // duration and fall back to vid_… (observed in a real search turn).
        if (props.command && props.command !== 'ingest') return
        // A job poll is also command 'ingest' and carries a job. Only a call with
        // a direct source owns the one-row direct table; letting a poll through
        // replaced a running shortlist batch with a single row (seen live when
        // the first jobs --wait returned: row 2 vanished and the table faded).
        if (!props.sourceHint) return
        if (props.bridge !== true || !job || !job.id || !sessionId) return
        const current = queueFor(sessionId)
        const createdMs = Date.parse(job.createdAt || '')
        const clearedAt = queueClearedAt(sessionId)
        // Remounting a historical ingest card must not recreate a queue the user
        // explicitly cleared (or a terminal queue that already faded).
        // A cleared session must not rebuild the table from an old card, but a
        // fresh direct ingest has no created_at (detached payload): only a
        // trustworthy timestamp older than the clear is rejected.
        // A replayed historical card (same job id) is still rejected after a
        // clear; only a trustworthy timestamp older than the clear also counts.
        const clearedIds = current ? [] : queueClearedRecord(sessionId).ids
        if (!current && clearedAt && (
          (job.id && clearedIds.includes(String(job.id)))
          || (createdMs && createdMs <= clearedAt)
        )) return
        // A direct job that is still running outlives the 5-minute window (a
        // 67-minute video); only a terminal stale card is history.
        const jobLive = job.state === 'running' || job.state === 'queued'
        if (!current && createdMs && !jobLive && Date.now() - createdMs > 5 * 60 * 1000) return
        // A live batch owns the table. A historical or duplicate direct card may
        // only refresh a row already in it; otherwise a remount of an old ingest
        // card wipes the batch that is currently running.
        const isTerminalState = (s) => s === 'ready' || s === 'failed' || s === 'canceled' || s === 'cancelled'
        if (current && Array.isArray(current.jobs) && current.jobs.length) {
          const mine = current.jobs.some((r) => r && r.job_id === job.id)
          // A card whose job this table has already seen is a historical remount,
          // not a new ingest: its first payload always says "running", so without
          // this the remount either appended a ghost row or was dropped entirely.
          const seen = Array.isArray(current.seenJobIds) ? current.seenJobIds : []
          const knownHistory = !!job.id && seen.includes(String(job.id))
          // The queue's own creation time is the other half of the test: a job
          // created before the table cannot be new to it.
          const queueCreated = Number(current.createdAt) || 0
          const olderThanTable = !!(createdMs && queueCreated && createdMs < queueCreated)
          if (!mine) {
            // A finished card is history and never creates a row.
            if (isTerminalState(job.state)) return
            // A replayed card only refreshes, even while a batch runs.
            if (knownHistory || olderThanTable) return
            // A folded table is user-authored state. A remount of a historical
            // ingest card still reports state "running" (the first tool result
            // always does), so it is indistinguishable from a new job; never
            // rewrite a folded table from a card mount. The job still shows as
            // a single card (LiveStrip allows it for a folded table).
            if (current.collapsed === true) return
          }
        }
        const source = job.source || String(props.sourceHint || '')
        // `resolve` returns `url`/`bvid`, not `video_id`; the first ingest payload
        // has neither. Match by the call's URL hint and by video id so the row gets
        // the title/cover from the model's resolve call on the first paint.
        const cached = [...RESOLVE_CACHE.values()].find((d) => d && (
          (job.videoId && String(d.video_id || '') === String(job.videoId))
          || (source && resolveUrlKey(d.url) === resolveUrlKey(source))
        ))
        // A Bilibili URL's last segment is a BV id, not a title. Keep the row
        // empty until resolve/overview fills it, so the table never flashes a
        // BV id before the real title.
        const urlTitle = /bilibili\.com|^BV[0-9A-Za-z]{10}$|^av\d+$/i.test(String(source || ''))
          ? ''
          : sourceName(source)
        const title = (overview && overview.title) || job.title || (cached && cached.title)
          || urlTitle || ''
        const row = {
          job_id: job.id,
          video_id: job.videoId || '',
          title,
          cover_url: (overview && overview.cover_url) || (cached && cached.cover_url) || '',
          source,
          uploader: (overview && overview.uploader) || (cached && cached.uploader) || '',
          duration_ms: (overview && overview.duration_ms) || (cached && cached.duration_ms) || job.durationMs || 0,
          state: job.state,
          stage: job.stage,
          error_message: job.errorMessage || job.errorCode || undefined,
          origin: 'direct',
        }
        // If our job is already in the table, merge its metadata and keep a
        // terminal state; a historical card must not demote a finished row back
        // to running or shrink a two-row batch to one.
        const existingRows = current && Array.isArray(current.jobs) ? current.jobs : []
        const idx = existingRows.findIndex((r) => r && r.job_id === job.id)
        const terminalState = (s) => s === 'ready' || s === 'failed' || s === 'canceled' || s === 'cancelled'
        // A retry of the same video must replace its row, not add a twin: after
        // three failed downloads the same three videos came back as six rows.
        // A row may carry only a video_id (no source) while the retry carries only
        // a source; compare the BV id inside either field as a last resort.
        // A BV id alone is not the identity: part 1 and part 2 of a multi-P video
        // share it. The page number is part of the key, and `p=1` is the same
        // video as no `p` at all (Python's canonical form drops it).
        const pageOf = (value) => {
          const m = /[?&]p=(\d+)/i.exec(String(value || ''))
          if (!m) return ''
          return m[1] === '1' ? '' : m[1]
        }
        const bvOf = (value) => {
          const m = /(BV[0-9A-Za-z]{10})/.exec(String(value || ''))
          return m ? m[1] : ''
        }
        const bvKey = (value) => {
          const bv = bvOf(value)
          return bv ? bv + '|' + pageOf(value) : ''
        }
        const sameVideo = (r) => {
          if (!r) return false
          if (row.video_id && String(r.video_id || '') === String(row.video_id)) return true
          if (row.source && resolveUrlKey(r.source) && resolveUrlKey(r.source) === resolveUrlKey(row.source)) return true
          const left = bvKey(row.video_id) || bvKey(row.source)
          const right = bvKey(r.video_id) || bvKey(r.source)
          return !!left && left === right
        }
        // Only metadata that describes the video is carried over; runtime flags
        // of the replaced job (`lost`, `canceling`, its error) must not stick to
        // the retry, or the new row is skipped as a lost job while it runs.
        const carried = (r) => {
          const { lost, canceling, error_message, error_code, remedy, ...rest } = r
          return rest
        }
        const retryIdx = idx >= 0 ? -1 : existingRows.findIndex(sameVideo)
        // A NEW direct ingest joins the table that is already on screen instead of
        // replacing it: replacing made a finished 2-video batch collapse into one
        // fresh card and look like the batch had been thrown away.
        const mergedRows = retryIdx >= 0
          ? existingRows.map((r, i) => {
            if (i !== retryIdx) return r
            // A finished row is never demoted back to running by a different job:
            // a historical ingest card always reports state "running" on mount,
            // and it used to overwrite the completed record.
            if (r.state === 'ready') return r
            // The mirror image: a historical failed card must not push a live
            // retry back to "未完成" while that retry is still working.
            if (isTerminalState(row.state) && !isTerminalState(r.state)) return r
            // A retry keeps the title/cover the row already had: the new payload
            // only carries the job id, and spreading it bare blanked the row.
            return {
              ...carried(r),
              ...row,
              title: row.title || r.title,
              cover_url: row.cover_url || r.cover_url,
              uploader: row.uploader || r.uploader,
              duration_ms: row.duration_ms || r.duration_ms,
            }
          })
          : idx >= 0
          ? existingRows.map((r, i) => (i === idx ? {
            ...r,
            ...row,
            // The detached payload has no title/cover yet: keep the row's known
            // metadata instead of overwriting it with empty strings.
            title: row.title || r.title,
            cover_url: row.cover_url || r.cover_url,
            uploader: row.uploader || r.uploader,
            duration_ms: row.duration_ms || r.duration_ms,
            state: terminalState(r.state) ? r.state : row.state,
          } : r))
          : [...existingRows, row]
        recordEvidence(sessionId, null)
        // Remember every job id this table has shown: a later remount of its card
        // is history, not a new ingest (its first payload is always "running").
        const seenNext = (() => {
          const base = (current && Array.isArray(current.seenJobIds)) ? current.seenJobIds.slice() : []
          const add = [String(job.id || '')].filter(Boolean)
          for (const id of add) if (!base.includes(id)) base.push(id)
          return base.slice(-50)
        })()
        storeQueue(sessionId, {
          createdAt: (current && current.createdAt) || Date.now(),
          jobs: mergedRows,
          seenJobIds: seenNext,
          // Merging keeps a folded table folded; replacing it with a new batch
          // must expand so the new rows are visible.
          collapsed: idx >= 0 && current ? current.collapsed === true : false,
          evidence: null,
        })
        // The first ingest result only carries the job id. The sidecar fills
        // `source`/`video_id` on the next poll and the resolve cache turns them into
        // a real title/cover, so the row must re-render when those arrive — waiting
        // for a stage change left the direct-link row saying "视频" for a while.
      }, [job && job.id, job && job.state, job && job.stage, job && job.videoId, job && job.source, overview && overview.title, sessionId])

      React.useEffect(() => {
        if (!jobId || !running) return undefined
        const createdMs = Date.parse((job && job.createdAt) || '')
        // Keep polling a live long job; stop only a card old enough that the job
        // itself must have ended.
        if (createdMs && Date.now() - createdMs > 30 * 60 * 1000
          && job.state !== 'running' && job.state !== 'queued') return undefined
        let alive = true
        let timer = null
        let fails = 0
        const tick = () => {
          fetch('/api/video2agent/job?id=' + encodeURIComponent(jobId))
            .then((r) => r.json())
            .then((payload) => {
              if (!alive) return
              if (payload && payload.job) {
                fails = 0
                setPollError('')
                const nextJob = normalizeJob(payload.job)
                setJob(nextJob)
                // Confirm for any known state, including failed: gating on
                // running meant a job that failed on its first poll never
                // published a live card and the failure stayed invisible.
                if (nextJob) setConfirmed(true)
                if (payload.overview) setOverview(payload.overview)
              } else {
                fails += 1
              }
            })
            .catch(() => { if (alive) fails += 1 })
            .then(() => {
              if (!alive) return
              if (fails >= 5) {
                // A deleted/pruned job used to poll every 15s forever; the card
                // is hidden anyway, so stop and leave one visible error.
                setPollError('进度更新中断，后台任务可能仍在运行；可稍后重试')
                alive = false
                return
              }
              // A poll costs one CLI start (~0.5s measured). At 1.2s that was ~43% of
              // a core for the whole job; 2.5s halves it and only delays a stage
              // label by 1.3s, while each stage lasts tens of seconds.
              const delay = fails ? Math.min(15000, 2500 * Math.pow(2, Math.min(fails - 1, 4))) : 2500
              timer = setTimeout(tick, delay)
            })
        }
        timer = setTimeout(tick, 900)
        return () => { alive = false; if (timer) clearTimeout(timer) }
      }, [jobId, running, retryNonce])

      if (!job) return null
      const failed = job.state === 'failed' || !!job.errorCode
      // A bridge is used by an ingest/job tool result only to drive the dock.
      // It must not leave a "thinking" card in conversation, but a failed job
      // still needs a visible error/remedy instead of disappearing with it.
      if (props.bridge === true && !failed) return null
      const pct = job.progress === null ? (job.state === 'ready' ? 100 : 0) : Math.round(Math.max(0, Math.min(1, job.progress)) * 100)
      const title = (overview && overview.title) || ''
      const duration = overview && overview.duration ? overview.duration : ''
      const created = job.createdAt ? Date.parse(job.createdAt) : 0
      const elapsed = created ? Date.now() - created : 0
      const ready = job.state === 'ready' || job.state === 'done'
      const phaseLabel = failed ? '失败' : ready ? '已就绪' : '处理中'
      const dot = failed ? 'err' : ready ? 'ok' : 'run'
      const stageText = ready ? '完成' : (job.message || job.stage || '进行中')
      // One surface per job: the strip above the composer owns live detail
      // (ring, stage, ETA, focus). This in-chat card is the record, so it keeps
      // the title, one plain status line, and the actions — no second progress
      // bar, no stage rail, no counts, and no job id.
      const line = [running ? pct + '%' : null, stageText, duration].filter(Boolean).join(' · ')

      return h('div', { 'data-vp-card': '' },
        h('div', { 'data-vp-head': '' },
          h('div', { 'data-vp-kicker': '' }, h('span', { 'data-vp-dot': dot }), 'VIDEO2AGENT · ' + phaseLabel),
          h('div', { 'data-vp-muted': '' }, running && elapsed ? '已用 ' + fmtClock(elapsed) : '')
        ),
        title ? h('div', { 'data-vp-title': '' }, title) : null,
        h('div', { 'data-vp-meta': '' }, line),
        running ? h(JobSteps, { stage: job.stage, done: false }) : null,
        pollError ? h('div', { 'data-vp-warn': '', style: { marginTop: '6px' } },
          pollError,
          h('button', {
            'data-vp-btn': '',
            style: { marginLeft: '8px' },
            onClick: () => { setPollError(''); setRetryNonce(retryNonce + 1) },
          }, '重试')
        ) : null,
        failed ? h('div', { 'data-vp-warn': 'err' },
          (job.errorCode ? job.errorCode + ' · ' : '') + (job.errorMessage || '处理失败'),
          job.remedy ? h('div', { 'data-vp-muted': '', style: { marginTop: '4px' } }, job.remedy) : null
        ) : null,
        ready ? h('div', { 'data-vp-foot': '' },
          h('div', { 'data-vp-muted': '' }, '证据索引可用'),
          h('div', { 'data-vp-actions': '' },
            job.videoId ? h('button', { 'data-vp-btn': 'primary', onClick: () => copyText(job.videoId) }, '复制 video_id') : null
          )
        ) : (failed ? null : h('div', { 'data-vp-foot': '' },
          h('div', { 'data-vp-muted': '' }, '后台运行，进度在输入框上方同步显示')
        ))
      )
    }

    function OverviewCard(props) {
      const data = props.data || {}
      const warnings = Array.isArray(data.warnings) ? data.warnings : []
      const statusText = [
        '已完成',
        data.duration ? '总长 ' + data.duration : '',
        '证据索引可用',
      ].filter(Boolean).join(' · ')
      return h('div', { 'data-vp-card': '', 'data-vp-done': '' },
        h('div', { 'data-vp-done-main': '' },
          h('span', { 'data-vp-done-badge': '', 'aria-hidden': 'true' },
            h('svg', { viewBox: '0 0 24 24' }, h('path', { d: 'M20 6 9 17l-5-5' }))
          ),
          h('div', { 'data-vp-done-body': '' },
            h('div', { 'data-vp-done-title': '' }, data.title || '视频'),
            h('div', { 'data-vp-done-sub': '' }, statusText)
          )
        ),
        warnings.length ? h('div', { 'data-vp-warn': '' }, warnings.map((w) => (w && (w.message || w.code)) || '').filter(Boolean).join(' / ')) : null
      )
    }

    function SearchCard(props) {
      const data = props.data || {}
      const results = Array.isArray(data.results) ? data.results : []
      const warnings = Array.isArray(data.warnings) ? data.warnings : []
      return h('div', { 'data-vp-card': '' },
        h('div', { 'data-vp-head': '' },
          h('div', { 'data-vp-kicker': '' }, 'VIDEO2AGENT · 检索'),
          h('div', { 'data-vp-muted': '' }, results.length + ' 条命中')
        ),
        h('div', { 'data-vp-title': '' }, '“' + String(data.query || '') + '”'),
        results.slice(0, 5).map((r, i) => h('div', { 'data-vp-row': '', key: r.evidence_id || i },
          h('span', { 'data-vp-time': '' }, r.timecode || fmtTime(r.start_ms)),
          h('div', { 'data-vp-rowmain': '' },
            h('div', { 'data-vp-rowtitle': '' }, String(r.snippet || '').slice(0, 160)),
            h('div', { 'data-vp-rowmeta': '' },
              h('span', {}, sourceLabel(r.source)),
              r.confidence !== undefined && r.confidence !== null ? h('span', {}, '置信 ' + Number(r.confidence).toFixed(2)) : null
            )
          )
        )),
        !results.length ? h('div', { 'data-vp-note': '', style: { marginTop: '6px' } }, '没有命中。换个关键词，或用 ≥2 个汉字/英文资源名再试。') : null,
        warnings.length ? h('div', { 'data-vp-warn': '' }, warnings.map((w) => (w && (w.message || w.code)) || '').filter(Boolean).join(' / ')) : null
      )
    }

    function EvidenceCard(props) {
      const data = props.data || {}
      const trans = Array.isArray(data.transcript) ? data.transcript : []
      const ocr = Array.isArray(data.ocr) ? data.ocr : []
      const images = Array.isArray(data.images) ? data.images : []
      const range = data.range || {}
      const tc = range.timecode || (trans[0] && fmtTime(trans[0].start_ms)) || ''
      return h('div', { 'data-vp-card': '' },
        h('div', { 'data-vp-head': '' },
          h('div', { 'data-vp-kicker': '' }, 'VIDEO2AGENT · 证据'),
          h('span', { 'data-vp-chip': '' }, tc)
        ),
        h('div', { 'data-vp-title': '' }, data.title || '证据包'),
        // Frames carry their timestamp: a picture without a timecode cannot be cited.
        images.length ? h('div', { 'data-vp-thumbs': '' }, images.slice(0, 4).map((p, i) => {
          const at = (data.frames && data.frames[i] && (data.frames[i].t_ms ?? data.frames[i].at_ms)) ?? null
          // Prefer the Host's opaque frame URL; a raw path stays only as the legacy
          // fallback for a card fed straight from CLI JSON in tests.
          const urls = Array.isArray(data.image_urls) ? data.image_urls : []
          const vid = String(data.video_id || '')
          const src = urls[i] || (vid
            ? '/api/video2agent/frame?id=' + encodeURIComponent(vid + '/' + String(p).split(/[\\/]/).pop())
            : '/api/video2agent/frame?path=' + encodeURIComponent(String(p)))
          return h('figure', { key: i, 'data-vp-shot': '' },
            h('img', {
              'data-vp-thumb': '',
              src,
              alt: 'evidence frame',
              loading: 'lazy',
            }),
            at !== null ? h('figcaption', { 'data-vp-shot-time': '' }, fmtTime(at)) : null
          )
        })) : null,
        trans.slice(0, 3).map((s, i) => h('div', { 'data-vp-row': '', key: 't' + i },
          h('span', { 'data-vp-time': '' }, fmtTime(s.start_ms)),
          h('div', { 'data-vp-rowmain': '' },
            h('div', { 'data-vp-rowtitle': '' }, s.text),
            h('div', { 'data-vp-rowmeta': '' }, h('span', {}, sourceLabel(field(s, 'source', 'transcript'))))
          )
        )),
        ocr.slice(0, 3).map((o, i) => h('div', { 'data-vp-row': '', key: 'o' + i },
          h('span', { 'data-vp-time': '' }, fmtTime(o.start_ms)),
          h('div', { 'data-vp-rowmain': '' },
            h('div', { 'data-vp-rowtitle': '' }, o.text),
            h('div', { 'data-vp-rowmeta': '' }, h('span', {}, '画面文字'))
          )
        )),
        h('div', { 'data-vp-foot': '' },
          h('div', { 'data-vp-muted': '' }, images.length + ' 帧 · ' + trans.length + ' 段语音 · ' + ocr.length + ' 条画面文字'),
          h('div', { 'data-vp-actions': '' },
            h('button', { 'data-vp-btn': '', onClick: () => copyText(data.citation || '') }, '复制引用')
          )
        )
      )
    }

    function ErrorCard(props) {
      const data = props.data || {}
      const err = data.error || {}
      return h('div', { 'data-vp-card': '', 'data-vp-tone': 'error' },
        h('div', { 'data-vp-head': '' },
          h('div', { 'data-vp-kicker': '' }, h('span', { 'data-vp-dot': 'err' }), 'VIDEO2AGENT · 未完成'),
          err.code ? h('span', { 'data-vp-chip': '', 'data-vp-chip-tone': 'err' }, String(err.code)) : null
        ),
        h('div', { 'data-vp-title': '' }, err.message || 'Video2Agent failed'),
        err.remedy
          ? h('div', { 'data-vp-remedy': '' },
            h('span', { 'data-vp-remedy-label': '' }, '怎么处理'),
            h('span', {}, String(err.remedy)))
          : null,
        props.onRetry
          ? h('div', { 'data-vp-foot': '' },
            h('div', { 'data-vp-muted': '' }, ''),
            h('div', { 'data-vp-actions': '' },
              h('button', { 'data-vp-btn': '', 'data-vp-btn-tone': 'primary', onClick: () => props.onRetry() }, '重试')
            ))
          : null
      )
    }

    function Card(props) {
      const block = props && props.block
      const args = parseCall(block)
      const text = resultText(block)
      const data = parseJson(text)
      const command = args && args.command ? String(args.command) : ''
      // The Host starts the selected videos inside shortlist and returns their job
      // rows. This is the only place a batch table is created; there is no pending
      // card, confirm route, or countdown to wait for.
      React.useEffect(() => {
        // The model-facing verb is ingest; video_ids is the shortlist form. The
        // Host returns the started rows under either verb, so the table must be
        // created for both — otherwise a real batch produced no batch card.
        const shortlistPayload = command === 'shortlist' || (command === 'ingest' && data && (
          (Array.isArray(data.jobs) && data.jobs.length)
          || (Array.isArray(data.queued) && data.queued.length)
          || (Array.isArray(data.failed) && data.failed.length)
        ))
        if (!shortlistPayload || !data) return
        const startedJobs = Array.isArray(data.jobs) ? data.jobs : []
        const queuedJobs = Array.isArray(data.queued) ? data.queued : []
        if (!startedJobs.length && !queuedJobs.length) return
        // A retried shortlist reuses the running batch; the existing table already
        // owns these job ids and must keep its retry/collapse state.
        if (data.reused === true) return
        const sid = sessionKey(props)
        if (!sid) return
        const rows = [...startedJobs, ...queuedJobs, ...(Array.isArray(data.failed) ? data.failed : [])]
          .filter((job) => job && (job.job_id || job.video_id))
          .map((job) => ({ ...job, origin: 'shortlist', state: job.state || (job.job_id ? 'running' : 'queued') }))
        if (!rows.length) return
        const startedAt = Number(data.started_at) || 0
        const current = queueFor(sid)
        const clearedAt = queueClearedAt(sid)
        // A cleared/faded batch must not be recreated by a historical shortlist
        // card when the conversation is reopened.
        if (!current && clearedAt && startedAt && startedAt <= clearedAt) return
        // A shortlist tool result is history once its batch is over. Without
        // this, opening any old conversation with a shortlist card recreated
        // its queue and replayed a running/completed card.
        if (!current && startedAt && Date.now() - startedAt > 5 * 60 * 1000) return
        // A historical shortlist card remounting after a reload must not replace a
        // newer batch that the same conversation already started. Equal timestamps
        // happen because the queue records the Host's started_at; treat them as the
        // same batch, not as a new one.
        if (current && current.createdAt && startedAt && current.createdAt >= startedAt) return
        // A new batch is a clean surface. Carrying still-running rows from an
        // older turn left stale BV-only rows in the table after a conversation
        // switch, which looked like the new batch but was minutes old.
        const nextJobs = rows
        LAST_BATCH_LIVE.delete(sid)
        recordEvidence(sid, null)
        storeQueue(sid, {
          createdAt: startedAt || Date.now(),
          batchId: data.batch_id || undefined,
          campaignId: data.campaign_id || undefined,
          jobs: nextJobs,
          collapsed: false,
          evidence: null,
        })
        const first = rows.find((job) => job.primary && job.job_id) || rows.find((job) => job.job_id)
        if (first && first.job_id) {
          publishLive({
            sessionId: sid,
            origin: 'batch',
            jobId: String(first.job_id),
            videoId: first.video_id || '',
            title: first.title || '',
            coverUrl: first.cover_url || '',
            duration: first.duration_ms ? fmtTime(first.duration_ms) : undefined,
            phase: 'running',
            pct: 0,
            stage: '已经启动，正在准备',
            createdAt: new Date().toISOString(),
          })
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [command, data && data.jobs && data.jobs.map((job) => job.job_id).join(','), data && data.started_at, sessionKey(props)])
      React.useEffect(() => {
        if (!data) return
        if (data.job_id || (data.id && String(data.id).startsWith('job_'))) return
        // A historical result card belongs to its own conversation: rendering it
        // must never rewrite the live strip owned by another session.
        const ownSession = sessionKey(props)
        if (ownSession && ACTIVE_SESSION && ownSession !== ACTIVE_SESSION) return
        // Resolve metadata is keyed by URL and is valid with or without a running
        // job: the direct-link table needs the title/cover from this call even when
        // the composer preview never resolved the link. This used to sit after the
        // live check, so a resolve before an ingest cached nothing.
        if (data.kind === 'video-link' && data.url) {
          RESOLVE_CACHE.set(data.url, data)
          RESOLVE_CACHE_TS.set(data.url, Date.now())
          if (RESOLVE_CACHE.size > 24) {
            const oldest = RESOLVE_CACHE.keys().next().value
            RESOLVE_CACHE.delete(oldest)
            RESOLVE_CACHE_TS.delete(oldest)
          }
        }
        const base = data.overview || data
        const ownLive = liveFor(ownSession || ACTIVE_SESSION)
        // Historical result cards must not create a live window on their own.
        if (!ownLive || (!ownLive.jobId && !ownLive.title && !ownLive.stage)) return
        const incomingVideo = base.video_id || data.video_id
        // A historical tool result must never rewrite a finished/cancelled live
        // card, even when it belongs to another video. Only a running card may be
        // enriched with focus/evidence.
        // closing is terminal too: a historical card must not flip 本轮结束 back to
        // a ready/running state (its payload has no jobId, so publishLive's own
        // closing guard cannot catch it).
        if (ownLive.phase === 'ready' || ownLive.phase === 'error'
            || ownLive.phase === 'canceled' || ownLive.phase === 'closing') return
        if (!base.title && !data.title && !(data.results && data.results.length) && !data.query) return
        const firstResult = data.results && data.results[0]
        const range = data.range || {}
        const focus = range.timecode || (range.start_ms !== undefined ? fmtTime(range.start_ms) : null) || (firstResult && (firstResult.timecode || (firstResult.start_ms !== undefined ? fmtTime(firstResult.start_ms) : null))) || (args && (args.at || args.start))
        const note = data.query || (data.transcript && data.transcript[0] && data.transcript[0].text) || (data.ocr && data.ocr[0] && data.ocr[0].text) || data.citation
        const running = ownLive && ownLive.phase === 'running'
        if (running) {
          // Historical result cards may enrich focus, but never rewrite the
          // running job's title, duration, session, or progress.
          publishLive({
            sessionId: ownSession || undefined,
            focusLabel: focus ? shortTimecode(focus) : undefined,
            focusNote: note ? String(note).slice(0, 52) : undefined,
          })
          return
        }
        const payload = {
          sessionId: ownSession || undefined,
          title: base.title || data.title,
          duration: base.duration || data.duration,
          videoId: base.video_id || data.video_id,
          coverUrl: base.cover_url || data.cover_url,
          focusLabel: focus ? shortTimecode(focus) : undefined,
          focusNote: note ? String(note).slice(0, 52) : undefined,
          clearFocus: !focus && (command === 'resolve' || command === 'ingest' || command === 'overview')
        }
        payload.pct = 100
        payload.phase = 'ready'
        payload.stage = focus ? '正在核对证据' : (command === 'overview' ? '已完成' : '正在分析视频')
        publishLive(payload)
      }, [block, data, command])
      // Keep the last evidence moment for the batch summary. This must run even
      // after the live card is gone, otherwise the one piece of proof the user can
      // read disappears exactly when the work finishes.
      React.useEffect(() => {
        if (!data) return
        // Only a real moment read, not every overview citation, belongs in the
        // completion receipt. The overview's citation is always 00:00:00.
        if (command !== 'evidence' && command !== 'search' && command !== 'frames') return
        const sid = sessionKey(props)
        if (!sid) return
        // A historical tool card remounts after reload too. Without this guard it
        // could re-create a receipt after 清除 or attach an old video's moment to
        // a new batch. Only the current queue's videos may write its chip.
        const queue = queueFor(sid)
        if (!queue || !Array.isArray(queue.jobs) || !queue.jobs.length) return
        const range = data.range || {}
        const first = (data.results || []).find((row) => row && row.source !== 'video_meta')
        if (!first && !range.timecode && range.start_ms === undefined) return
        const evidenceVideo = data.video_id || (first && first.video_id)
        if (evidenceVideo && !queue.jobs.some((job) => job.video_id === evidenceVideo)) return
        const timecode = range.timecode
          || (range.start_ms !== undefined ? fmtTime(range.start_ms) : '')
          || (first && (first.timecode || (first.start_ms !== undefined ? fmtTime(first.start_ms) : '')))
          || (data.query ? '' : '')
        const note = data.query
          || (data.ocr && data.ocr[0] && data.ocr[0].text)
          || (data.transcript && data.transcript[0] && data.transcript[0].text)
          || data.citation
        if (!timecode && !note) return
        recordEvidence(sid, {
          timecode: timecode ? shortTimecode(timecode) : '',
          note: note ? String(note).replace(/\s+/g, ' ').slice(0, 72) : '',
        })
      }, [command, data && data.citation, data && data.query, data && data.range && data.range.timecode, data && data.results && data.results.length, sessionKey(props)])

      if (block && block.isError) {
        return h('div', { 'data-vp-card': '' },
          h('div', { 'data-vp-head': '' },
            h('div', { 'data-vp-kicker': '' }, h('span', { 'data-vp-dot': 'err' }), 'VIDEO2AGENT'),
            h('div', { 'data-vp-muted': '' }, command || 'error')
          ),
          h('div', { 'data-vp-warn': 'err' }, text.slice(0, 600) || 'Video2Agent failed')
        )
      }

      // search/shortlist progress lives in the dock, not as a chat tool card.
      if (!data) {
        if (text && text.trim()) {
          return h(ErrorCard, { data: { error: { code: 'E_RESULT', message: text.slice(0, 600) } } })
        }
        // No "waiting…" card. The dock owns search/job progress; a tool card that
        // only says it is thinking is the exact clutter reported on 2026-10-28.
        return null
      }

      if (data.ok === false) {
        return h(ErrorCard, { data: data.error ? data : { error: { code: 'E_RESULT', message: text.slice(0, 600) || 'Video2Agent failed' } } })
      }
      // A shortlist result is a batch table in the dock, never a chat job card.
      // The model calls it as ingest with video_ids, so match the payload, not
      // only the legacy shortlist verb; otherwise a JobCard also writes a
      // one-row queue and the batch table is lost.
      if (Array.isArray(data.jobs) || Array.isArray(data.queued) || (Array.isArray(data.failed) && data.state === 'started')) return null
      if (command === 'shortlist') return null
      if (command === 'doctor' || command === 'list') return null
      // transcript carries a host-attached overview so the completion card renders
      // even when the model skipped a separate overview call.
      if (data.overview && data.overview.counts) return h(OverviewCard, { data: data.overview })
      if (data.kind === 'video-link') return h(LinkCard, { data, command })
      // Raw discover results are input for the model, not a chat card. Publishing
      // them here produced one eight-item card per search (ten in the 2026-10-28
      // draft turn). The single dock card is driven by /discovery/pending after the
      // model calls shortlist.
      if (Array.isArray(data.candidates)) return null
      // Ingest/job polling is a process, not a chat message. The dock owns it;
      // render no bubble and no second progress card here.
      if (data.job_id || data.state || data.id && String(data.id).indexOf('job_') === 0) return h(JobCard, { data, sessionId: sessionKey(props), bridge: true, sourceHint: (args && (args.source || args.url)) || '', command })
      if (command === 'jobs') return null
      if (data.citation || data.evidence_id) return h(EvidenceCard, { data })
      if (Array.isArray(data.results) || data.query) return h(SearchCard, { data })
      if (data.counts || data.capabilities) return h(OverviewCard, { data })

      return h('div', { 'data-vp-card': '' },
        h('div', { 'data-vp-head': '' },
          h('div', { 'data-vp-kicker': '' }, 'VIDEO2AGENT'),
          h('div', { 'data-vp-muted': '' }, field(data, 'title', command || 'result'))
        ),
        h('pre', { 'data-vp-pre': '' }, JSON.stringify(data, null, 2).slice(0, 900))
      )
    }

    // Environment check + one-click install. The plugin cannot run the Python
    // CLI by itself, so this card is where a new user finds out what is missing
    // and fixes it without a terminal. Installs are initiated here only.
    function EnvironmentCard() {
      const [setup, setSetup] = React.useState({ state: 'loading', data: null })
      const [busy, setBusy] = React.useState('')
      const [log, setLog] = React.useState('')
      const load = async () => {
        if (busy) return
        setBusy('refresh')
        try {
          const response = await fetch('/api/video2agent/setup')
          const data = await response.json().catch(() => null)
          if (!response.ok || !data || data.ok === false) throw new Error('read failed')
          setSetup({ state: 'ready', data })
          setLog('')
        } catch {
          setSetup((current) => ({ ...current, state: 'error' }))
        } finally {
          setBusy('')
        }
      }
      React.useEffect(() => { load() }, [])
      const install = async (action) => {
        setBusy(action)
        setLog('正在安装…首次约 1–3 分钟，请保持这个页面打开；失败时会显示原因。')
        try {
          const response = await fetch('/api/video2agent/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action }),
          })
          const data = await response.json().catch(() => null)
          if (data && data.status) setSetup({ state: 'ready', data: data.status })
          if (!response.ok || !data || data.ok !== true) {
            const error = (data && data.error && [data.error.message, data.error.remedy].filter(Boolean).join('：'))
              || (data && (data.error || data.detail))
              || ('安装失败（HTTP ' + response.status + '）')
            setLog(String(error) + (data && data.output ? '\n' + data.output : ''))
          } else if (data.output) {
            setLog(data.output)
          }
        } catch (e) {
          setLog(String((e && e.message) || e))
        } finally {
          setBusy('')
        }
      }
      const data = setup.data
      // Compact: one status line with three chips, install buttons only for what is
      // missing. The full version/path text stays in the chip's tooltip.
      const items = data ? [
        { key: 'python', label: 'Python', item: data.python, text: data.python && data.python.ok ? String(data.python.detail || '').replace(/^Python\s*/, '') : '缺失' },
        { key: 'cli', label: 'CLI', item: data.cli, text: data.cli && data.cli.ok ? String(data.cli.detail || '').replace(/^video2agent\s*/, '') : '缺失' },
        { key: 'ffmpeg', label: 'FFmpeg', item: data.ffmpeg, text: (() => {
          if (!data.ffmpeg || !data.ffmpeg.ok) return '缺失'
          const match = String(data.ffmpeg.detail || '').match(/ffmpeg version (\d+(?:\.\d+)*)/i)
          return match ? match[1] : '正常'
        })() },
        // Optional: local on-screen-text OCR. Only meaningful once the CLI works;
        // both OCR engines (rapidocr 3.x, rapidocr-onnxruntime) are installable.
        ...(data.cli && data.cli.ok && data.ocr
          ? [{ key: 'ocr', label: 'OCR', item: data.ocr, text: data.ocr.ok ? '已装' : (data.ocr.supported ? '未装' : '不支持') }]
          : []),
      ] : []
      const missing = items.filter((entry) => !(entry.item && entry.item.ok))
      // The Python CLI carries the platform fixes (macOS Keychain key storage,
      // OCR engines). A CLI that is merely installed but older than this npm
      // build must offer an update button — otherwise the page cannot fix the
      // exact DPAPI error the user is looking at.
      const updateCli = !!(data && data.canInstall && data.canInstall.updateCli)
      const chip = (entry) => {
        const ok = !!(entry.item && entry.item.ok)
        return h('span', { key: entry.key, 'data-vp-env-state': ok ? 'ok' : 'missing', 'data-vp-env-item': entry.key,
          title: entry.item && entry.item.detail ? entry.item.detail : '',
          style: { display: 'inline-flex', alignItems: 'center', gap: '5px', padding: '1px 7px', borderRadius: '999px',
            background: ok ? 'rgba(46,160,67,.10)' : 'rgba(217,83,79,.10)', color: ok ? '#1a7f37' : '#b42318',
            fontSize: '11px', lineHeight: '18px', whiteSpace: 'nowrap' } },
          h('span', { style: { width: '6px', height: '6px', borderRadius: '50%', background: ok ? '#2ea043' : '#d9534f', flex: 'none' } }),
          entry.label + ' ' + entry.text,
        )
      }
      return h('div', { 'data-vp-env': '', 'data-vp-cloud': '', style: { margin: '0 0 12px', padding: '9px 12px' } },
        h('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' } },
          h('div', { style: { display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', minWidth: 0 } },
            h('span', { style: { fontSize: '12.5px', fontWeight: 650, marginRight: '2px' } }, '环境检查'),
            setup.state === 'loading' || (!data && setup.state !== 'error')
              ? h('span', { style: { fontSize: '11.5px', opacity: '.65' } }, '检测中…')
              : setup.state === 'error'
                ? h('span', { style: { fontSize: '11.5px', color: '#b42318' } }, '读取失败')
                : items.map(chip),
          ),
          h('button', { 'data-vp-bili-btn': '', disabled: !!busy, onClick: () => load(),
            style: { flex: 'none', padding: '2px 8px', fontSize: '11px', lineHeight: '18px' } }, busy ? '…' : '重新检测'),
        ),
        updateCli
          ? h('div', { style: { display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', marginTop: '7px' } },
              h('span', { style: { fontSize: '11px', color: '#9a6700' } },
                'CLI 可更新：' + (data.cli.version || '?') + ' → ' + (data.cli.latest || '?')),
              h('button', {
                'data-vp-bili-btn': '',
                disabled: !!busy,
                onClick: () => install('update-cli'),
                style: { padding: '2px 8px', fontSize: '11px', lineHeight: '18px' },
              }, busy === 'update-cli' ? '更新中…' : '更新 CLI'),
            )
          : null,
        missing.length
          ? h('div', { style: { display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', marginTop: '7px' } },
              h('span', { style: { fontSize: '11px', color: 'var(--vp-muted,#63605a)' } }, '缺少依赖：'),
              missing.map((entry) => {
                const action = entry.key === 'cli' ? 'install-cli' : entry.key === 'ffmpeg' ? 'install-ffmpeg' : entry.key === 'ocr' ? 'install-ocr' : ''
                return action && data.canInstall && data.canInstall[entry.key]
                  ? h('button', { key: entry.key, 'data-vp-bili-btn': '', disabled: !!busy, onClick: () => install(action),
                      style: { padding: '2px 8px', fontSize: '11px', lineHeight: '18px' } },
                      busy === action ? '安装中…' : ('安装 ' + entry.label))
                  : h('span', { key: entry.key, style: { fontSize: '11px', color: '#b42318' } }, entry.label + ' 需要手动安装')
              }),
            )
          : null,
        missing.some((entry) => entry.key === 'python')
          ? h('div', { style: { fontSize: '11px', color: 'var(--vp-muted,#63605a)', marginTop: '6px' } }, (data && data.hints && data.hints.python) || '先安装 Python 3.11+。')
          : null,
        log ? h('pre', { 'data-vp-env-log': '', style: { marginTop: '6px', maxHeight: '120px', overflow: 'auto', fontSize: '10.5px', whiteSpace: 'pre-wrap' } }, log) : null,
      )
    }

    function SettingsSection(props) {
      const settings = useSettings()
      const settingsState = useSettingsState()
      const [draft, setDraft] = React.useState(settings)
      const [saveState, setSaveState] = React.useState('idle')
      // Bilibili login state: the QR flow is what makes "use the subtitles"
      // possible without a user ever touching a cookie file.
      const [bili, setBili] = React.useState(() => BILI_CACHE || { loggedIn: false, uid: '', qr: '', key: '', state: 'loading', busy: false })
      // A data: URL can still fail to decode (WebKit/Chromium differences, a
      // truncated response); show a retry hint instead of a blank white box.
      const [qrFailed, setQrFailed] = React.useState(false)
      React.useEffect(() => { setQrFailed(false) }, [bili.qr])
      const [cloud, setCloud] = React.useState(() => CLOUD_CACHE || { state: 'loading', configured: false, last4: '', ocrEnabled: false, error: '' })
      const [cloudDraft, setCloudDraft] = React.useState(() => CLOUD_DRAFT_CACHE || { provider: 'siliconflow', base_url: 'https://api.siliconflow.cn/v1', asr_model: '', ocr_model: '', asr_enabled: true })
      const [cloudKey, setCloudKey] = React.useState('')
      const [cloudBusy, setCloudBusy] = React.useState('')
      const [models, setModels] = React.useState(() => MODELS_CACHE || { state: 'loading', asr: { selected: 'small', cached: false }, tiers: [], tier: 'mid' })
      const [modelChoice, setModelChoice] = React.useState(() => (MODELS_CACHE && MODELS_CACHE.tier) || 'small')
      const [modelCustom, setModelCustom] = React.useState(() => (MODELS_CACHE && MODELS_CACHE.custom && MODELS_CACHE.asr && MODELS_CACHE.asr.selected) || '')
      const [modelBusy, setModelBusy] = React.useState(false)
      const [ocrCustomMode, setOcrCustomMode] = React.useState(() => !!(MODELS_CACHE && MODELS_CACHE.ocr && MODELS_CACHE.ocr.selected === 'custom'))
      const [ocrConfig, setOcrConfig] = React.useState(() => (MODELS_CACHE && MODELS_CACHE.ocr && MODELS_CACHE.ocr.config_path) || '')
      const saveTimer = React.useRef(null)
      const saveStateTimer = React.useRef(null)
      const pendingUi = React.useRef({})
      React.useEffect(() => () => { if (saveStateTimer.current) clearTimeout(saveStateTimer.current) }, [])
      // A hydrate that lands while the user is editing must not overwrite the
      // draft: only sync while the draft is clean, and clear the flag once the
      // pending patch has been saved.
      const draftDirty = React.useRef(false)
      // A failed patch must be retried by the next save; dropping it made the
      // next unrelated success silently revert the failed field on the server.
      const failedUi = React.useRef({})
      React.useEffect(() => { if (!draftDirty.current) setDraft(settings) }, [settings])
      React.useEffect(() => { CLOUD_CACHE = cloud; persistSettingsCache({ cloud }) }, [cloud])
      React.useEffect(() => { CLOUD_DRAFT_CACHE = cloudDraft; persistSettingsCache({ cloudDraft }) }, [cloudDraft])
      React.useEffect(() => { MODELS_CACHE = models; persistSettingsCache({ models }) }, [models])
      React.useEffect(() => {
        // Never persist the QR image or a transient busy state.
        BILI_CACHE = { loggedIn: !!bili.loggedIn, uid: bili.uid || '', state: bili.state === 'ready' ? 'ready' : 'loading' }
        persistSettingsCache({ bili: BILI_CACHE })
      }, [bili.loggedIn, bili.uid, bili.state])
      React.useEffect(() => {
        let alive = true
        fetch('/api/video2agent/models')
          .then(async (r) => {
            let d = null
            try { d = await r.json() } catch {}
            // A 500 or an ok:false payload is a failed read. Returning here left the
            // panel showing initial defaults ("当前：small · 未下载") as if measured.
            if (!r.ok || !d || d.ok === false) throw new Error('models read failed')
            return d
          })
          .then((d) => {
            if (!alive) return
            setModels({ ...d, state: 'ready' })
            const selected = (d.asr && d.asr.selected) || 'small'
            setModelChoice(d.tier || 'custom')
            setModelCustom(d.custom ? selected : '')
            setOcrCustomMode(!!(d.ocr && d.ocr.selected === 'custom'))
            setOcrConfig((d.ocr && d.ocr.config_path) || '')
          })
          .catch(() => { if (alive) setModels((m) => ({ ...m, state: 'error' })) })
        return () => { alive = false }
      }, [])
      const modelValue = modelChoice === 'custom' ? modelCustom.trim() : modelChoice
      const downloadModel = async () => {
        if (!modelValue) { setModels((m) => ({ ...m, error: '填写模型 ID 或本地路径' })); return }
        setModelBusy(true)
        try {
          const response = await fetch('/api/video2agent/models', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'download', model: modelValue }),
          })
          const data = await response.json().catch(() => null)
          if (!data || data.ok === false) throw new Error((data && data.error && data.error.message) || '下载失败')
          setModels((m) => ({ ...m, asr: { ...(m.asr || {}), selected: data.model, cached: true, bytes: data.bytes || 0, path: data.path }, error: '' }))
        } catch (e) {
          setModels((m) => ({ ...m, error: String((e && e.message) || e) }))
        } finally {
          setModelBusy(false)
        }
      }
      const selectModel = async (value = modelValue, download = false) => {
        const chosen = String(value || '').trim()
        if (!chosen) { setModels((m) => ({ ...m, error: '填写模型 ID 或本地路径' })); return }
        setModelBusy(true)
        try {
          const response = await fetch('/api/video2agent/models', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'select', model: chosen }),
          })
          const data = await response.json().catch(() => null)
          if (!data || data.ok === false) throw new Error((data && data.error && data.error.message) || '保存失败')
          setModels({ ...data, state: 'ready', error: '' })
          setModelChoice(data.tier || 'custom')
          setModelCustom(data.custom ? ((data.asr && data.asr.selected) || chosen) : '')
          if (download) {
            const dlResponse = await fetch('/api/video2agent/models', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ action: 'download', model: chosen }),
            })
            const dl = await dlResponse.json().catch(() => null)
            if (!dl || dl.ok === false) throw new Error((dl && dl.error && dl.error.message) || '下载失败')
            setModels((m) => ({ ...m, asr: { ...(m.asr || {}), selected: dl.model || chosen, cached: true, bytes: dl.bytes || 0, path: dl.path }, error: '' }))
          }
        } catch (e) {
          setModels((m) => ({ ...m, error: String((e && e.message) || e) }))
        } finally {
          setModelBusy(false)
        }
      }
      const uninstallModel = async () => {
        const selected = (models.asr && models.asr.selected) || ''
        if (!selected) return
        if (typeof window !== 'undefined' && !window.confirm('卸载本机 ASR 模型 ' + selected + '？')) return
        setModelBusy(true)
        try {
          const response = await fetch('/api/video2agent/models', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'uninstall', model: selected }),
          })
          const data = await response.json().catch(() => null)
          if (!data || data.ok === false) throw new Error((data && data.error && data.error.message) || '卸载失败')
          setModels({ ...data, state: 'ready', error: '' })
        } catch (e) {
          setModels((m) => ({ ...m, error: String((e && e.message) || e) }))
        } finally {
          setModelBusy(false)
        }
      }
      const selectOcrModel = async (configPath = '') => {
        setModelBusy(true)
        try {
          const response = await fetch('/api/video2agent/models', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'select-ocr', ocr_config: configPath }),
          })
          const data = await response.json().catch(() => null)
          if (!data || data.ok === false) throw new Error((data && data.error && data.error.message) || '保存 OCR 模型失败')
          setModels({ ...data, state: 'ready', error: '' })
          setOcrCustomMode(!!(data.ocr && data.ocr.selected === 'custom'))
          setOcrConfig((data.ocr && data.ocr.config_path) || '')
        } catch (e) {
          setModels((m) => ({ ...m, error: String((e && e.message) || e) }))
        } finally {
          setModelBusy(false)
        }
      }
      React.useEffect(() => {
        let alive = true
        fetch('/api/video2agent/cloud')
          .then(async (r) => {
            let d = null
            try { d = await r.json() } catch {}
            if (!r.ok || !d || d.ok === false) throw new Error('cloud read failed')
            return d
          })
          .then((d) => {
            if (!alive) return
            setCloud((c) => ({ ...c, ...d, state: 'ready', error: '' }))
            setCloudDraft({
              provider: d.provider || 'siliconflow',
              base_url: d.base_url || 'https://api.siliconflow.cn/v1',
              asr_model: d.asr_model || '',
              ocr_model: d.ocr_model || '',
              asr_enabled: d.asr_enabled !== false,
            })
          })
          .catch(() => { if (alive) setCloud((c) => ({ ...c, state: 'error', error: '读取云端配置失败' })) })
        return () => { alive = false }
      }, [])
      const cloudAction = async (action, extra = {}) => {
        setCloudBusy(action)
        try {
          const response = await fetch('/api/video2agent/cloud', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, ...extra }),
          })
          const data = await response.json().catch(() => null)
          if (!data || data.ok === false) throw new Error((data && data.error && data.error.message) || '请求失败')
          setCloud((c) => ({
            ...c,
            ...data,
            // The Host reports what is really in effect: an environment key
            // survives a clear, so 'key_cleared' alone must not turn cloud off.
            ...(action === 'config' && typeof data.configured === 'boolean'
              ? { configured: data.configured, last4: data.last4 || '', source: data.source || null }
              : (action === 'config' && data.key_cleared ? { configured: false, last4: '', source: null } : {})),
            state: 'ready',
            error: '',
            testMessage: action === 'test'
              ? ('凭据有效 · ' + (data.models_seen || 0) + ' 个模型 · 未检查余额' + ((data.asr_available === false || data.ocr_available === false) ? ' · 部分默认模型未列出' : ''))
              : action === 'clear' ? ''
                : (action === 'config' && data.key_cleared ? '配置已保存；服务商已切换，请重新填写 Key。' : c.testMessage),
          }))
          if (action === 'config') {
            setCloudDraft((d) => ({
              ...d,
              provider: data.provider || d.provider,
              base_url: data.base_url || d.base_url,
              asr_model: data.asr_model || d.asr_model,
              ocr_model: data.ocr_model || d.ocr_model,
              asr_enabled: data.asr_enabled !== undefined ? data.asr_enabled !== false : d.asr_enabled,
            }))
          }
          if (action === 'save') setCloudKey('')
          return data
        } catch (e) {
          setCloud((c) => ({ ...c, error: String((e && e.message) || e) }))
          return null
        } finally {
          setCloudBusy('')
        }
      }
      React.useEffect(() => {
        let alive = true
        fetch('/api/video2agent/bili-login/status')
          .then((r) => { if (!r.ok) throw new Error('http ' + r.status); return r.json() })
          .then((d) => {
            if (!alive) return
            // A 502/ok:false is "unknown", not "logged out": showing 未登录
            // makes the user scan the QR again for a transient error.
            if (!d || d.ok === false) throw new Error((d && d.error) || 'status failed')
            setBili((b) => ({ ...b, loggedIn: !!d.logged_in, uid: d.uid || '', state: 'ready' }))
          })
          .catch(() => setBili((b) => ({ ...b, state: 'error' })))
        return () => { alive = false }
      }, [])
      React.useEffect(() => {
        if (!bili.key || typeof setInterval !== 'function') return undefined
        const key = bili.key
        let busy = false
        let done = false
        const apply = (patch) => setBili((b) => (b.key === key ? { ...b, ...patch } : b))
        const finish = () => { done = true; clearInterval(timer) }
        const confirmedElsewhere = async () => {
          try {
            const response = await fetch('/api/video2agent/bili-login/status')
            const data = await response.json()
            if (data && data.ok !== false && data.logged_in) {
              finish()
              apply({ loggedIn: true, uid: data.uid || '', qr: '', key: '', state: 'ok', error: '' })
              return true
            }
          } catch {}
          return false
        }
        const timer = setInterval(async () => {
          // Two polls on the same key race each other: Bilibili answers the
          // confirmed one with code 0 and any later one with 86038 ("expired").
          // Without this guard the late answer painted 二维码已过期 right after a
          // successful login.
          if (busy || done) return
          busy = true
          try {
            const response = await fetch('/api/video2agent/bili-login/poll?key=' + encodeURIComponent(key))
            const data = await response.json().catch(() => null)
            if (!data) return
            if (data.state === 'ok') {
              finish()
              apply({ loggedIn: true, uid: data.uid || '', qr: '', key: '', state: 'ok', error: '' })
            } else if (data.state === 'scanned') {
              apply({ state: 'scanned', error: '' })
            } else if (data.state === 'failed') {
              finish()
              apply({ qr: '', state: 'failed', error: data.error || '扫码已确认，但没拿到登录态，请重新生成二维码。' })
            } else if (data.state === 'expired') {
              finish()
              // The login may have been saved even if this poll saw a consumed key.
              if (!(await confirmedElsewhere())) apply({ qr: '', state: 'expired', error: '' })
            }
          } catch {
            /* transient network error: the next tick retries */
          } finally {
            busy = false
          }
        }, 2000)
        return () => clearInterval(timer)
      }, [bili.key])
      const biliStart = async () => {
        setBili((b) => ({ ...b, busy: true, state: 'idle' }))
        try {
          // The route requires a JSON POST: a cross-site "simple" text/plain POST
          // must not be able to start or clear a login. The body is empty on
          // purpose, but the header has to be explicit.
          const response = await fetch('/api/video2agent/bili-login/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
          })
          const data = await response.json()
          if (!data || !data.qr) throw new Error('no qr')
          setBili((b) => ({ ...b, qr: data.qr, key: data.key, state: 'pending', busy: false }))
        } catch {
          setBili((b) => ({ ...b, busy: false, state: 'error', error: '生成二维码失败，请稍后再试。' }))
        }
      }
      const biliClear = async () => {
        try {
          const response = await fetch('/api/video2agent/bili-login/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
          })
          const data = await response.json().catch(() => ({}))
          if (!response.ok || (data && data.ok === false)) throw new Error('clear failed')
        } catch {
          // A failed clear must not look like a successful logout.
          setBili((b) => ({ ...b, state: 'error', busy: false, error: '退出登录失败，请稍后再试。' }))
          return
        }
        setBili({ loggedIn: false, uid: '', qr: '', key: '', state: 'idle', busy: false })
      }
      if (props && props.view === 'summary') {
        return h('div', { 'data-vp-settings-summary': '' }, '云端 ASR/OCR、B站账号、处理卡片、主题色和缓存。')
      }
      const persistUi = async (patch) => {
        // POST only what changed. The old body always carried four defaults, so a
        // failed read followed by one click overwrote the other three settings.
        const body = {}
        if ('enabled' in patch) body.enabled = !!patch.enabled
        if ('cacheTtlMs' in patch) body.cacheTtlMs = Number(patch.cacheTtlMs) || 24 * 60 * 60 * 1000
        if ('cacheExpire' in patch) body.cacheExpire = !!patch.cacheExpire
        if ('cacheDays' in patch) body.cacheDays = Math.max(1, Math.min(365, Number(patch.cacheDays) || 7))
        if ('cacheLimitEnabled' in patch) body.cacheLimitEnabled = !!patch.cacheLimitEnabled
        if ('cacheLimitGb' in patch) body.cacheLimitGb = Math.max(1, Math.min(20, Number(patch.cacheLimitGb) || 20))
        if ('accentColor' in patch) body.accentColor = accentHex(patch.accentColor)
        if ('processLimit' in patch) body.processLimit = Math.max(1, Math.min(10, Number(patch.processLimit) || 10))
        if (!Object.keys(body).length) return
        // Read the live store, not the render-time closure: a GET that fails
        // after this render must still block the write, and a later successful
        // hydrate must unblock it without a remount.
        if (SETTINGS_STATE === 'error' && !SETTINGS_CORRUPT) {
          // The page is showing defaults, not the stored values. Refuse the write
          // instead of saving a guess; the read-error banner already explains
          // why, so do not also claim "保存失败". Roll the controls back too:
          // keeping the edit on screen looked saved and blocked the next save.
          // Do not clear a previous 保存失败: it must stay until a save succeeds.
          draftDirty.current = false
          setDraft({ ...(SETTINGS_ACKED || SETTINGS || DEFAULT_SETTINGS) })
          return
        }
        const outgoing = { ...failedUi.current, ...body }
        const ok = await saveSettings(outgoing)
        if (ok) {
          if (SETTINGS_CORRUPT) {
            // The save rewrote the corrupt file: clear the banner by re-reading.
            SETTINGS_CORRUPT = false
            hydrateSettings()
          }
          failedUi.current = {}
          draftDirty.current = false
          setSaveState('saved')
          // Only a badge that still says "saved" may go idle. A bare timeout
          // cleared a later 保存失败 after its own 1.2s, so the page said
          // "自动保存" while the server still had the old value.
          if (saveStateTimer.current) clearTimeout(saveStateTimer.current)
          saveStateTimer.current = setTimeout(() => {
            saveStateTimer.current = null
            setSaveState((current) => (current === 'saved' ? 'idle' : current))
          }, 1200)
        } else {
          // Keep the failure visible until a save actually succeeds. A 3s flash
          // left the control showing the new value while the server still had the
          // old one: the user thought the change was saved. Keep the patch too,
          // so the next save retries it instead of silently dropping it.
          failedUi.current = { ...failedUi.current, ...body }
          setSaveState('error')
        }
      }
      const updateUi = (patch) => {
        const next = { ...draft, ...patch }
        draftDirty.current = true
        setDraft(next)
        // Accumulate: two controls changed inside the 300ms window used to post
        // only the last key, so the first change looked saved and reverted on
        // reload. persistUi already sends only the keys in its argument.
        pendingUi.current = { ...pendingUi.current, ...patch }
        if (saveTimer.current) clearTimeout(saveTimer.current)
        saveTimer.current = setTimeout(() => {
          const body = pendingUi.current
          pendingUi.current = {}
          saveTimer.current = null
          persistUi(body)
        }, 300)
      }
      const accent = accentHex(draft.accentColor)
      const saveCloudConfig = (patch = {}) => {
        const current = { ...cloudDraft, ...patch }
        const provider = current.provider || 'siliconflow'
        const base = String(current.base_url || '').trim()
        if (!base) { setCloud((c) => ({ ...c, error: '填写 Base URL' })); return }
        cloudAction('config', {
          provider,
          base_url: base,
          asr_model: String(current.asr_model || '').trim(),
          ocr_model: String(current.ocr_model || '').trim(),
          asr_enabled: current.asr_enabled !== false,
        })
      }
      const chooseProvider = (provider) => {
        const preset = (cloud.presets || []).find((p) => p.id === provider)
        setCloudDraft((d) => ({
          ...d,
          provider,
          base_url: preset && preset.base_url
            ? preset.base_url
            : (provider === 'siliconflow' ? 'https://api.siliconflow.cn/v1' : (d.provider === 'custom' ? d.base_url : '')),
        }))
      }
      const biliStatus = bili.state === 'loading'
        ? '读取中…'
        : bili.state === 'error'
          // A failed status read is unknown, not logged out; a failed start/clear
          // keeps the last known login state and names the action instead.
          ? (bili.error && bili.loggedIn ? '已登录' : bili.error ? '未登录' : '读取失败')
          : bili.loggedIn
            ? ('已登录' + (bili.uid ? ' · UID ' + bili.uid : ''))
            : '未登录'
      // The capsule must show the server's confirmed mode, not the optimistic
      // draft: a failed save left it saying 本地 while audio still went to the
      // provider.
      // A failed cloud read is "unknown", not "local": claiming 本地 would
      // assert a source the page never learned.
      const cloudUnknown = cloud.state === 'error'
      const asrCloud = !cloudUnknown && !!cloud.configured && cloud.asr_enabled !== false
      const ocrCloud = !cloudUnknown && !!cloud.configured && cloud.ocr_enabled
      const asrSource = cloudUnknown ? '未知' : (asrCloud ? '云端' : '本地')
      const ocrSource = cloudUnknown ? '未知' : (ocrCloud ? '云端' : '本地')
      // The same Key-store error came from both the status read and a failed save;
      // render it once instead of stacking two identical red lines.
      const keyErrorMessage = cloud.key_error && cloud.key_error.message ? String(cloud.key_error.message) : ''
      // Local OCR is a separate Python extra; on a machine that cannot install it
      // (e.g. Python 3.13 has no rapidocr wheel) the page must say so instead of
      // offering a dead "内置" dropdown that looks installed.
      const ocrLocal = models.ocr || {}
      const ocrLocalAvailable = models.state === 'ready' && !!ocrLocal.available

      return h('div', { 'data-vp-settings': '', 'data-loading': (cloud.state === 'loading' || models.state === 'loading') ? '1' : undefined },
        h('h1', { 'data-vp-settings-title': '' }, 'Video2Agent'),
        h('p', { 'data-vp-settings-note': '' }, '环境检查、云模型、B 站、本机模型和界面设置。'),

        EnvironmentCard(),

        h('div', { 'data-vp-cloud': '' },
          h('div', { 'data-vp-bili-head': '' },
            h('span', { 'data-vp-bili-title': '' }, '获取 API Key'),
          ),
          h('div', { 'data-vp-bili-hint': '', style: { marginTop: '4px', fontWeight: '600' } }, '无需充值，即刻白嫖'),
          h('div', { 'data-vp-bili-actions': '', style: { marginTop: '8px', flexWrap: 'wrap' } },
            h('a', { href: cloud.invite_url || 'https://cloud.siliconflow.cn/i/gFnkeTR4', target: '_blank', rel: 'noreferrer noopener', 'data-vp-bili-btn': '', 'data-vp-site': 'cn' }, '国内站 · 邀请注册'),
            h('a', { href: cloud.international_url || 'https://www.siliconflow.com', target: '_blank', rel: 'noreferrer noopener', 'data-vp-bili-btn': '', 'data-vp-site': 'intl' }, '国际站 · 无邀请码')
          ),
          h('div', { 'data-vp-bili-actions': '', style: { marginTop: '8px', flexWrap: 'wrap' } },
            h('input', {
              type: 'password',
              value: cloudKey,
              placeholder: cloud.configured ? '已保存，输入新 Key 可替换' : '粘贴 API Key',
              autoComplete: 'new-password',
              spellCheck: 'false',
              style: { flex: '1', minWidth: '180px', padding: '7px 9px', borderRadius: '9px' },
              onChange: (e) => setCloudKey(e.target.value),
            }),
            h('button', { 'data-vp-bili-btn': '', disabled: !!cloudBusy || !cloudKey.trim(), onClick: () => cloudAction('save', { key: cloudKey }) }, cloudBusy === 'save' ? '保存中…' : '保存 Key'),
            h('button', { 'data-vp-bili-btn': '', disabled: !!cloudBusy || !cloud.configured, onClick: () => cloudAction('test') }, cloudBusy === 'test' ? '测试中…' : '测试连接'),
            h('button', {
              'data-vp-bili-btn': '',
              disabled: !!cloudBusy || !cloud.configured || cloud.source === 'env',
              onClick: () => {
                if (typeof window !== 'undefined' && !window.confirm('清除已保存的 API Key？')) return
                cloudAction('clear')
              },
            }, '清除')
          ),
          h('div', { 'data-vp-bili-hint': '', style: { marginTop: '4px' } }, '国内站注册可获得赠金，并支持作者的肥鱼获得更多米饭！(๑•̀ㅂ•́)و✧'),
          cloud.source === 'env' ? h('div', { 'data-vp-bili-hint': '', style: { marginTop: '4px' } }, '当前使用环境变量中的 Key；请在启动环境中移除。') : null,
          cloud.testMessage ? h('div', { 'data-vp-bili-hint': '', style: { marginTop: '4px' } }, cloud.testMessage) : null,
          cloud.key_error ? h('div', { 'data-vp-warn': 'err', style: { marginTop: '6px' } }, cloud.key_error.message || '保存的 Key 无法解密，请重新保存。') : null,
          cloud.error ? h('div', { 'data-vp-warn': 'err', style: { marginTop: '6px' } }, cloud.error) : null
        ),
        h('div', { 'data-vp-cloud': '' },
          h('div', { 'data-vp-bili-head': '' },
            h('span', { 'data-vp-bili-title': '' }, '云端服务'),
            h('span', { 'data-vp-bili-state': '' }, '兼容 OpenAI 接口')
          ),
          h('div', { 'data-vp-bili-hint': '', style: { marginTop: '6px' } }, '服务商'),
          h('select', {
            value: cloudDraft.provider || 'siliconflow',
            style: { width: '100%', padding: '7px 9px', borderRadius: '9px' },
            onChange: (e) => chooseProvider(e.target.value),
          },
            (cloud.presets || [{ id: 'siliconflow', label: 'SiliconFlow' }, { id: 'custom', label: '自定义（OpenAI 兼容）' }]).map((p) =>
              h('option', { key: p.id, value: p.id }, p.label)
            )
          ),
          h('div', { 'data-vp-bili-hint': '', style: { marginTop: '6px' } }, 'Base URL'),
          h('input', {
            type: 'url', value: cloudDraft.base_url || '', placeholder: 'https://api.example.com/v1',
            spellCheck: 'false',
            style: { width: '100%', padding: '7px 9px', borderRadius: '9px' },
            onChange: (e) => setCloudDraft((d) => ({ ...d, base_url: e.target.value })),
          }),
          h('div', { 'data-vp-bili-head': '', style: { marginTop: '14px' } },
            h('span', { 'data-vp-bili-title': '' }, '语音识别 ASR'),
            h('span', { 'data-vp-bili-state': asrCloud ? 'on' : 'off' }, asrSource)
          ),
          h('div', { 'data-vp-settings-row': '', style: { marginTop: '2px' } },
            h('span', {}, '来源'),
            h('div', { 'data-vp-seg': '', role: 'group', 'aria-label': 'ASR 来源' },
              h('button', {
                type: 'button',
                'data-on': asrCloud ? '1' : '0',
                'aria-pressed': !!asrCloud,
                disabled: !!cloudBusy || !cloud.configured,
                onClick: () => {
                  if (asrCloud) return
                  setCloudDraft((d) => ({ ...d, asr_enabled: true }))
                  saveCloudConfig({ asr_enabled: true })
                },
              }, '云端 ASR'),
              h('button', {
                type: 'button',
                'data-on': asrCloud ? '0' : '1',
                'aria-pressed': !asrCloud,
                onClick: () => {
                  if (!asrCloud) return
                  setCloudDraft((d) => ({ ...d, asr_enabled: false }))
                  saveCloudConfig({ asr_enabled: false })
                },
              }, '本地 ASR')
            )
          ),
          cloudUnknown
            ? h('div', { 'data-vp-bili-hint': '', 'data-vp-cloud-need-key': '', style: { marginTop: '4px' } },
                '读取云端配置失败，暂时无法判断来源')
            : !cloud.configured
              ? h('div', { 'data-vp-bili-hint': '', 'data-vp-cloud-need-key': '', style: { marginTop: '4px' } },
                  '先粘贴 API Key 才能用云端')
            : null,
          asrCloud
            ? h('div', { 'data-vp-bili-hint': '', 'data-vp-upload-note': 'asr', style: { marginTop: '4px' } },
                '音频会发送给你配置的服务商')
            : null,
          asrCloud
            ? h('div', null,
                h('div', { 'data-vp-bili-hint': '', style: { marginTop: '6px' } }, '云端 ASR 模型'),
                h('input', {
                  type: 'text', value: cloudDraft.asr_model || '', placeholder: '任意 ASR 模型 ID',
                  spellCheck: 'false',
                  style: { width: '100%', padding: '7px 9px', borderRadius: '9px' },
                  onChange: (e) => setCloudDraft((d) => ({ ...d, asr_model: e.target.value })),
                })
              )
            : h('div', null,
                h('select', {
                  value: modelChoice || models.tier || 'custom',
                  disabled: models.state !== 'ready' || modelBusy,
                  style: { width: '100%', marginTop: '6px', padding: '7px 9px', borderRadius: '9px' },
                  onChange: (e) => {
                    const tier = (models.tiers || []).find((t) => t.id === e.target.value)
                    setModelChoice(e.target.value)
                    if (tier) selectModel(tier.model)
                  },
                },
                  (models.tiers || []).map((t) => h('option', { key: t.id, value: t.id }, t.label + ' · ' + t.model + ' · ' + t.size + (t.cpu_short ? ' · ' + t.cpu_short : ''))),
                  h('option', { value: 'custom' }, '高级：自定义模型 ID / 本地路径')
                ),
                modelChoice === 'custom' ? h('div', null,
                  h('div', { 'data-vp-bili-actions': '', style: { marginTop: '6px', flexWrap: 'wrap' } },
                    h('input', {
                      type: 'text', value: modelCustom, placeholder: 'HuggingFace 模型 ID（自动下载）或本地路径',
                      spellCheck: 'false',
                      style: { flex: '1', minWidth: '220px', padding: '7px 9px', borderRadius: '9px' },
                      onChange: (e) => setModelCustom(e.target.value),
                    }),
                    h('button', { 'data-vp-bili-btn': '', disabled: modelBusy || !modelCustom.trim(), onClick: () => selectModel(modelCustom, true) }, modelBusy ? '处理中…' : '下载并使用')
                  ),
                  h('div', { 'data-vp-bili-hint': '', style: { marginTop: '4px' } }, '填 HuggingFace 模型 ID 会自动下载；例如 deepdml/faster-whisper-large-v3-turbo-ct2')
                ) : null,
                h('div', { 'data-vp-bili-actions': '', style: { marginTop: '8px', flexWrap: 'wrap' } },
                  h('span', { 'data-vp-bili-hint': '', 'data-vp-model-state': models.state, style: { flex: '1' } },
                    models.state === 'error'
                      ? '当前：读取失败'
                      : models.state === 'ready'
                        ? '当前：' + ((models.asr && models.asr.selected) || '未选择') + (models.asr && models.asr.cached ? ' · 已下载' : ' · 未下载')
                        : '当前：读取中…'),
                  h('button', { 'data-vp-bili-btn': '', disabled: models.state !== 'ready' || modelBusy || !!(models.asr && models.asr.cached), onClick: downloadModel }, modelBusy ? '下载中…' : ((models.asr && models.asr.cached) ? '已下载' : '下载并加载')),
                  h('button', { 'data-vp-bili-btn': '', disabled: models.state !== 'ready' || modelBusy || !(models.asr && models.asr.cached) || !!models.custom, onClick: uninstallModel }, '卸载')
                )
              ),
          h('div', { 'data-vp-bili-head': '', style: { marginTop: '14px' } },
            h('span', { 'data-vp-bili-title': '' }, '画面文字 OCR'),
            h('span', { 'data-vp-bili-state': ocrCloud ? 'on' : 'off' }, ocrSource)
          ),
          h('div', { 'data-vp-settings-row': '', style: { marginTop: '2px' } },
            h('span', {}, '来源'),
            h('div', { 'data-vp-seg': '', role: 'group', 'aria-label': 'OCR 来源' },
              h('button', {
                type: 'button',
                'data-on': ocrCloud ? '1' : '0',
                'aria-pressed': !!ocrCloud,
                disabled: !!cloudBusy || !cloud.configured,
                onClick: () => {
                  if (ocrCloud) return
                  cloudAction('ocr', { enabled: true })
                },
              }, '云端 OCR'),
              h('button', {
                type: 'button',
                'data-on': ocrCloud ? '0' : '1',
                'aria-pressed': !ocrCloud,
                onClick: () => {
                  if (!ocrCloud) return
                  cloudAction('ocr', { enabled: false })
                },
              }, '本地 OCR')
            )
          ),
          cloudUnknown
            ? h('div', { 'data-vp-bili-hint': '', 'data-vp-cloud-need-key': '', style: { marginTop: '4px' } },
                '读取云端配置失败，暂时无法判断来源')
            : !cloud.configured
              ? h('div', { 'data-vp-bili-hint': '', 'data-vp-cloud-need-key': '', style: { marginTop: '4px' } },
                  '先粘贴 API Key 才能用云端')
            : null,
          ocrCloud
            ? h('div', { 'data-vp-bili-hint': '', 'data-vp-upload-note': 'ocr', style: { marginTop: '4px' } },
                '画面会发送给你配置的服务商')
            : null,
          ocrCloud
            ? h('div', null,
                h('div', { 'data-vp-bili-hint': '', style: { marginTop: '6px' } }, '云端 OCR 模型'),
                h('input', {
                  type: 'text', value: cloudDraft.ocr_model || '', placeholder: '任意视觉 OCR 模型 ID',
                  spellCheck: 'false',
                  style: { width: '100%', padding: '7px 9px', borderRadius: '9px' },
                  onChange: (e) => setCloudDraft((d) => ({ ...d, ocr_model: e.target.value })),
                })
              )
            : h('div', null,
                !ocrLocalAvailable && models.state === 'ready'
                  ? h('div', { 'data-vp-warn': 'err', 'data-vp-ocr-missing': '', style: { marginTop: '6px' } },
                      '本地 OCR 未安装。可在上方「环境检查」里点「安装 OCR」（可选）；也可以改用云端 OCR（先保存 API Key）。')
                  : null,
                h('select', {
                  value: ocrCustomMode ? 'custom' : 'builtin',
                  disabled: models.state !== 'ready' || modelBusy || !ocrLocalAvailable,
                  style: { width: '100%', marginTop: '6px', padding: '7px 9px', borderRadius: '9px' },
                  onChange: (e) => {
                    const custom = e.target.value === 'custom'
                    setOcrCustomMode(custom)
                    if (!custom) selectOcrModel('')
                  },
                },
                  h('option', { value: 'builtin' }, 'RapidOCR · ' + (ocrLocal.model || 'PP-OCR') + '（' + (ocrLocalAvailable ? '内置' : '需要先安装本地 OCR') + '）'),
                  h('option', { value: 'custom' }, '高级：自定义模型 ID / 本地路径')
                ),
                ocrCustomMode ? h('div', null,
                  h('div', { 'data-vp-bili-actions': '', style: { marginTop: '6px', flexWrap: 'wrap' } },
                    h('input', {
                      type: 'text', value: ocrConfig, placeholder: 'HuggingFace 模型 ID（自动下载）或本地路径',
                      spellCheck: 'false',
                      style: { flex: '1', minWidth: '200px', padding: '7px 9px', borderRadius: '9px' },
                      onChange: (e) => setOcrConfig(e.target.value),
                    }),
                    h('button', { 'data-vp-bili-btn': '', disabled: modelBusy || !ocrConfig.trim(), onClick: () => selectOcrModel(ocrConfig) }, modelBusy ? '下载中…' : '下载并使用')
                  ),
                  h('div', { 'data-vp-bili-hint': '', style: { marginTop: '4px' } }, '填 HuggingFace 模型 ID 会自动下载；例如 SWHL/RapidOCR')
                ) : null,
                h('div', { 'data-vp-bili-hint': '', 'data-vp-visual-index': '', style: { marginTop: '4px' } },
                  '默认按需识别，可手动建立画面索引。')
              ),
          models.state === 'error'
            ? h('div', { 'data-vp-warn': 'err', 'data-vp-models-error': '', style: { marginTop: '8px' } },
                '读取本机模型失败：ASR/OCR 的当前状态不可信，请刷新页面重试。')
            : null,
          h('div', { 'data-vp-bili-actions': '', style: { marginTop: '10px', flexWrap: 'wrap' } },
            // Saving while the current config is unknown would post defaults and
            // could clear the stored key (provider/base change -> clear_key).
            h('button', { 'data-vp-bili-btn': '', disabled: !!cloudBusy || cloud.state === 'error', onClick: saveCloudConfig }, cloudBusy === 'config' ? '保存中…' : '保存配置')
          ),
          h('div', { 'data-vp-bili-hint': '', style: { marginTop: '8px' } },
            '默认模型免费；具体定价请前往',
            h('a', { href: 'https://cloud.siliconflow.cn', target: '_blank', rel: 'noreferrer noopener', style: { color: 'var(--vp-accent)' } }, '硅基流动官网'),
            '查看。'
          ),
          // role=alert so screen readers announce a failed read/save instead of
          // leaving it as an unlabelled visual hint.
          cloud.error && cloud.error !== keyErrorMessage ? h('div', { 'data-vp-warn': 'err', role: 'alert', style: { marginTop: '8px' } }, cloud.error) : null,
          models.error ? h('div', { 'data-vp-warn': 'err', role: 'alert', style: { marginTop: '8px' } }, models.error) : null
        ),
        h('div', { 'data-vp-bili': '' },
          h('div', { 'data-vp-bili-head': '' },
            h('span', { 'data-vp-bili-title': '' }, 'B 站登录'),
            h('span', { 'data-vp-bili-state': bili.loggedIn ? 'on' : 'off' }, biliStatus)
          ),
          h('div', { 'data-vp-bili-hint': '' },
            '扫码登录，优先使用 B 站字幕。'),
          bili.qr ? h('div', { 'data-vp-bili-qrbox': '' },
            qrFailed
              ? h('div', { 'data-vp-warn': 'err', role: 'alert' }, '二维码图片加载失败，请点「重新生成二维码」重试。')
              : h('img', {
                  'data-vp-bili-qr': '',
                  src: bili.qr,
                  alt: 'B 站登录二维码',
                  onError: () => setQrFailed(true),
                  onLoad: (e) => { if (!e.target || !e.target.naturalWidth) setQrFailed(true) },
                }),
            h('div', { 'data-vp-bili-tip': '' }, bili.state === 'scanned' ? '已扫码，请在手机上点确认' : '用 B 站手机 App 扫码登录')
          ) : null,
          bili.state === 'expired' ? h('div', { 'data-vp-warn': '', style: { marginTop: '8px' } }, '二维码已超时，请重新生成') : null,
          bili.state === 'failed' ? h('div', { 'data-vp-warn': 'err', style: { marginTop: '8px' } },
            bili.error || '扫码已确认，但没拿到登录态，请重新生成二维码再扫一次。') : null,
          bili.state === 'error' ? h('div', { 'data-vp-warn': 'err', role: 'alert', style: { marginTop: '8px' } },
            bili.error || '读取登录状态失败，可重新扫码或稍后再试。') : null,
          h('div', { 'data-vp-bili-actions': '' },
            h('button', { 'data-vp-bili-btn': '', onClick: biliStart, disabled: bili.busy }, bili.qr ? '重新生成二维码' : '扫码登录'),
            bili.loggedIn ? h('button', { 'data-vp-bili-btn': '', onClick: biliClear }, '退出登录') : null
          )
        ),
        h('div', { 'data-vp-bili-head': '', style: { marginTop: '6px' } },
          h('span', { 'data-vp-bili-title': '' }, '界面与处理'),
          h('span', {
            'data-vp-bili-state': (saveState === 'error' || settingsState === 'error') ? 'err' : 'on',
          }, settingsState === 'error' ? '读取失败' : saveState === 'error' ? '保存失败' : '自动保存')
        ),
        settingsState === 'error'
          ? h('div', { 'data-vp-warn': 'err', 'data-vp-settings-read-error': '', style: { marginTop: '6px' } },
              h('span', {}, SETTINGS_CORRUPT
                ? '设置文件已损坏：修改任意一项并保存即可重建它。'
                : '读取设置失败：下面显示的可能不是服务器当前值，修改已回滚。'),
              h('button', {
                'data-vp-settings-retry': '',
                style: { marginLeft: '8px' },
                onClick: () => { setSettingsState('loading'); hydrateSettings() },
              }, '重试'))
          : null,
        saveState === 'error'
          ? h('div', { 'data-vp-warn': 'err', 'data-vp-save-error': '', style: { marginTop: '6px' } },
              '保存失败：服务器没有接受这次修改，刷新页面可恢复旧值。')
          : null,
        h('label', { 'data-vp-settings-row': '' },
          h('span', {}, '显示处理卡片'),
          h('input', { type: 'checkbox', checked: !!draft.enabled, onChange: (e) => updateUi({ enabled: e.target.checked }) })
        ),
        h('label', { 'data-vp-settings-row': '' },
          h('span', {}, '主题色'),
          h('div', { 'data-vp-swatches': '' },
            ACCENT_PRESETS.map((preset) => h('button', {
              key: preset.value,
              type: 'button',
              title: preset.label,
              'aria-label': preset.label,
              'data-vp-swatch': accent === preset.value ? 'on' : '',
              style: { background: preset.value },
              onClick: () => updateUi({ accentColor: preset.value }),
            })),
            h('span', { 'data-vp-colorlabel': '' }, '自定义'),
            h('input', {
              type: 'color',
              value: accent,
              'aria-label': '自定义主题色',
              'data-vp-color': '',
              onChange: (e) => updateUi({ accentColor: e.target.value }),
            })
          )
        ),
        h('div', { 'data-vp-settings-row': '', 'data-vp-process-row': '' },
          h('span', {}, '单次处理上限'),
          h('div', { 'data-vp-process-control': '' },
            h('input', {
              type: 'range',
              min: 1,
              max: 10,
              step: 1,
              value: Math.max(1, Math.min(10, Number(draft.processLimit) || 10)),
              'data-vp-process-limit': '',
              'aria-label': '单次处理上限',
              onChange: (e) => updateUi({ processLimit: Math.max(1, Math.min(10, Number(e.target.value) || 1)) }),
            }),
            h('b', { 'data-vp-process-value': '' }, String(Math.max(1, Math.min(10, Number(draft.processLimit) || 10))) + ' 个')
          )
        ),
        h('label', { 'data-vp-settings-row': '' },
          h('span', {}, '链接预览缓存'),
          h('select', { value: draft.cacheTtlMs, onChange: (e) => updateUi({ cacheTtlMs: Number(e.target.value) }) },
            h('option', { value: 60 * 60 * 1000 }, '1 小时'),
            h('option', { value: 24 * 60 * 60 * 1000 }, '24 小时'),
            h('option', { value: 7 * 24 * 60 * 60 * 1000 }, '7 天'),
            h('option', { value: 30 * 24 * 60 * 60 * 1000 }, '30 天')
          )
        ),
        h('div', { 'data-vp-settings-row': '', 'data-vp-cache-expire': '' },
          h('label', { style: { display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' } },
            h('span', {}, '缓存到期删除'),
            h('input', { type: 'checkbox', checked: draft.cacheExpire !== false, onChange: (e) => updateUi({ cacheExpire: e.target.checked }) })
          ),
          h('div', { style: { display: 'flex', alignItems: 'center', gap: '6px' } },
            h('span', { 'data-vp-muted': '' }, '保留'),
            h('select', {
              'data-vp-cache-days': '',
              'aria-label': '缓存保留天数',
              value: Math.max(1, Math.min(365, Number(draft.cacheDays) || 7)),
              disabled: draft.cacheExpire === false,
              onChange: (e) => updateUi({ cacheDays: Number(e.target.value) }),
            },
              [3, 7, 14, 30, 90].map((days) => h('option', { key: days, value: days }, days + ' 天'))
            )
          )
        ),
        h('div', { 'data-vp-settings-row': '', 'data-vp-cache-limit': '' },
          h('label', { style: { display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' } },
            h('span', {}, '限制缓存容量'),
            h('input', { type: 'checkbox', checked: draft.cacheLimitEnabled === true, onChange: (e) => updateUi({ cacheLimitEnabled: e.target.checked }) })
          ),
          h('div', { style: { display: 'flex', alignItems: 'center', gap: '6px' } },
            h('span', { 'data-vp-muted': '' }, '上限'),
            h('select', {
              'data-vp-cache-limit-gb': '',
              'aria-label': '缓存容量上限',
              value: Math.max(1, Math.min(20, Number(draft.cacheLimitGb) || 20)),
              disabled: draft.cacheLimitEnabled !== true,
              onChange: (e) => updateUi({ cacheLimitGb: Number(e.target.value) }),
            },
              [5, 10, 20].map((gb) => h('option', { key: gb, value: gb }, gb + ' GB'))
            )
          )
        )
      )
    }

    const COVER_HOSTS = /(^|\.)(hdslb\.com|biliimg\.com|bilivideo\.com)$/i
    // Bilibili refuses hot-linked covers (403 without its referer), so platform
    // covers go through the Host proxy; anything else is used as-is.
    function coverThrough(url) {
      let raw = String(url || '').trim()
      if (!raw) return ''
      if (raw.indexOf('/api/video2agent/cover') === 0) return raw
      if (raw.indexOf('//') === 0) raw = 'https:' + raw
      try {
        const parsed = new URL(raw)
        if (!/^https?:$/.test(parsed.protocol)) return ''
        // The Host proxy accepts HTTPS only. Bilibili often hands back
        // http://i0.hdslb.com/...; upgrade the CDN URL instead of returning a
        // 400 that leaves every queue row with the fallback triangle.
        if (parsed.protocol === 'http:' && COVER_HOSTS.test(parsed.hostname)) parsed.protocol = 'https:'
        return COVER_HOSTS.test(parsed.hostname)
          ? '/api/video2agent/cover?u=' + encodeURIComponent(parsed.toString())
          : parsed.toString()
      } catch {
        return ''
      }
    }

    function displayTitleFor(job) {
      const raw = String(job && job.title || '').trim()
      if (raw && !/^BV[0-9A-Za-z]{10}$|^av\d+$/i.test(raw)) return raw
      return '视频'
    }

    function fmtCount(value) {
      const n = Number(value)
      if (!Number.isFinite(n) || n <= 0) return ''
      if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
      if (n >= 10000) return (n / 10000).toFixed(1) + '万'
      return String(Math.round(n))
    }

    // A generic card for the few long actions that are not ingest jobs.
    // It only says what the action is doing; no counts, no stage, no error text.
    function ActivityStrip(props) {
      const sid = sessionKey(props)
      const queue = useQueue(sid)
      const live = useLive(sid)
      const [activity, setActivity] = React.useState(null)
      const [hidden, setHidden] = React.useState(false)
      const settings = useSettings()
      React.useEffect(() => {
        if (!settings.enabled) return undefined
        let alive = true
        let timer = null
        setActivity(null)
        setHidden(false)
        const tick = async () => {
          try {
            const url = '/api/video2agent/activity' + (sid ? '?session=' + encodeURIComponent(sid) : '')
            const response = await fetch(url)
            // A single 500 used to return before the reschedule below and stop
            // polling forever, leaving a stale 正在处理 card on screen.
            if (!response.ok) throw new Error('http ' + response.status)
            const data = await response.json()
            if (alive) setActivity(data && data.activity ? data.activity : null)
          } catch {}
          if (alive) timer = setTimeout(tick, typeof document !== 'undefined' && document.hidden ? 10000 : 2500)
        }
        tick()
        return () => { alive = false; if (timer) clearTimeout(timer) }
      }, [sid, settings.enabled])
      React.useEffect(() => {
        if (!activity) { setHidden(false); return undefined }
        if (activity.state === 'running') { setHidden(false); return undefined }
        const at = Number(activity.finished_at || activity.at || 0)
        const remaining = Math.max(0, 8000 - (Date.now() - at))
        const timer = setTimeout(() => setHidden(true), remaining)
        return () => clearTimeout(timer)
      }, [activity && activity.id, activity && activity.state, activity && (activity.finished_at || activity.at)])
      if (!settings.enabled) return null
      const jobs = queue && Array.isArray(queue.jobs) ? queue.jobs : []
      if (jobs.length) return null
      if (live && live.hidden !== true) return null
      if (!activity || hidden) return null
      const label = activity.state === 'ready' ? '已完成' : activity.state === 'failed' ? '未完成' : '正在处理'
      const title = String(activity.title || '')
      return h('div', { 'data-vp-live': '', 'data-vp-activity': '', 'data-phase': activity.state === 'ready' ? 'ready' : activity.state === 'failed' ? 'error' : 'running', role: 'status', 'aria-live': 'polite' },
        h('div', { 'data-vp-live-main': '' },
          h('div', { 'data-vp-live-body': '' },
            title ? h('div', { 'data-vp-live-title': '', title }, title) : null,
            h('div', { 'data-vp-live-sub': '' }, label))))
    }

    function LiveStrip(props) {
      const sid = sessionKey(props)
      if (typeof window !== 'undefined' && window.__VIDEO2AGENT_DEBUG__ === true) {
        // QA hook: what does the dock slot actually hand us? (Does the session
        // object carry a `running` flag the turn-end wrap-up can rely on?)
        window.__video2agentLastSessionProps = props && props.session
          ? { keys: Object.keys(props.session), id: props.session.id, running: props.session.running }
          : null
      }
      const live = useLive(sid || ACTIVE_SESSION)
      const settings = useSettings()
      // When the batch table is on screen it owns the surface: its header ring
      // and rows already say which video, what stage and how to stop. Keeping a
      // second cover/title card above it would duplicate the same job.
      const dockQueue = useQueue(sid || ACTIVE_SESSION)
      const [dismissed, setDismissed] = React.useState(null)
      const [leaving, setLeaving] = React.useState(false)
      React.useEffect(() => {
        if (!sid) return
        ACTIVE_SESSION = sid
        publishSession(sid)
      }, [sid])
      // "The turn ended" is the strongest completion signal we get: when the
      // assistant stops running, the card wraps up instead of hanging until the
      // watchdog notices.
      const sessionRunning = props && props.session && typeof props.session.running === 'boolean' ? props.session.running : undefined
      React.useEffect(() => {
        if (!sid || sessionRunning === undefined) return
        if (sessionRunning) { SESSION_WAS_RUNNING.add(sid); return }
        if (!SESSION_WAS_RUNNING.has(sid)) return
        SESSION_WAS_RUNNING.delete(sid)
        closeLive(sid, liveFor(sid))
      }, [sid, sessionRunning])
      React.useEffect(() => {
        if (!live) return undefined
        if (live.hidden === true) return undefined
        if (live.phase !== 'ready' && live.phase !== 'error' && live.phase !== 'canceled'
          && live.phase !== 'cancelled' && live.phase !== 'closing') {
          setDismissed(null); setLeaving(false); return undefined
        }
        // A terminal video status is done even if the assistant is still composing.
        // Never wait for whole-session idleness; the hidden latch prevents later
        // history cards from reviving it.
        let exitTimer = null
        // Failure is shown as the same short status as success; the reason
        // belongs in the answer, not in a card that lingers.
        const terminalAt = Number(live.finishedAt || live.updatedAt || 0)
        const hold = live.phase === 'closing' ? 3000 : CARD_HOLD_MS
        const remaining = Math.max(0, hold - (Date.now() - terminalAt))
        const timer = setTimeout(() => {
          setLeaving(true)
          exitTimer = setTimeout(() => {
            setDismissed(terminalAt)
            publishLive({ sessionId: sid || undefined, hidden: true, hiddenAt: Date.now() })
          }, 180)
        }, remaining)
        return () => { clearTimeout(timer); if (exitTimer) clearTimeout(exitTimer) }
      }, [live && live.phase, live && (live.finishedAt || live.updatedAt)])
      React.useEffect(() => { if (!live || !live.hidden) setLeaving(false) }, [live && live.updatedAt, live && live.hidden])
      if (!settings.enabled) return null
      const queueJobs = dockQueue && Array.isArray(dockQueue.jobs) ? dockQueue.jobs : []
      const queueRunning = queueJobs.some((job) => job && job.state !== 'ready' && job.state !== 'failed'
        && job.state !== 'canceled' && job.state !== 'cancelled')
      // The batch table owns the surface whenever it has any row (running,
      // canceled, or just-finished). Letting LiveStrip render after a terminal
      // row was cleared produced the alternating "table → single card → table"
      // duplicate in the live UI.
      // Exception: a folded table shows only a pill, so a job that is not one of
      // its rows still needs the single card (otherwise a new ingest is invisible).
      const foldedForeignJob = !!(dockQueue && dockQueue.collapsed === true && live && live.jobId
        && !queueJobs.some((job) => job && String(job.job_id) === String(live.jobId)))
      if (queueJobs.length && !foldedForeignJob) return null
      if (queueRunning) return null
      if (live && live.jobId && queueJobs.some((job) => String(job.job_id) === String(live.jobId))) return null
      if (!live || (!live.title && !live.stage)) return null
      if (sid && live.sessionId && live.sessionId !== sid) return null
      if (live.hidden === true) return null
      // Do not paint a running card whose last update is older than the watchdog
      // stale window; that was the ghost seen when reopening a conversation.
      if (live.phase === 'running' && Date.now() - Number(live.updatedAt || 0) > 5000) return null
      if (dismissed !== null && dismissed === (live.finishedAt || live.updatedAt)) return null
      const liveTerminal = live.phase === 'ready' || live.phase === 'error'
        || live.phase === 'canceled' || live.phase === 'cancelled'
      const terminalAt = Number(live.finishedAt || live.updatedAt || 0)
      const terminalLimit = live.phase === 'closing' ? 3000 : CARD_HOLD_MS
      if ((liveTerminal || live.phase === 'closing')
          && terminalAt && Date.now() - terminalAt >= terminalLimit) return null
      const pct = Math.max(0, Math.min(100, Math.round(Number(live.pct || 0))))
      const sub = live.phase === 'error'
        ? '未完成'
        : live.phase === 'canceled' || live.phase === 'cancelled'
          ? '已取消'
          : live.phase === 'closing'
            ? '本轮结束'
            : live.phase === 'ready'
              ? '已完成'
              : '正在处理'
      const ringR = 29
      const ringC = 2 * Math.PI * ringR
      const ringOffset = live.phase === 'error' ? ringC : ringC * (1 - pct / 100)
      // Bilibili covers 403 without a referer; the table already proxies them, and
      // the processing card used the raw URL and showed an empty ring instead.
      const liveCover = live.coverUrl
        ? (String(live.coverUrl).indexOf('/api/video2agent/cover') === 0 ? String(live.coverUrl) : coverThrough(live.coverUrl))
        : ''
      // Icon paths are Lucide (ISC), inlined so the plugin needs no extra runtime.
      return h('div', { 'data-vp-live': '', 'data-phase': live.phase, 'data-leaving': leaving ? 'true' : undefined, role: 'status', 'aria-live': 'polite', 'aria-label': (live.phase === 'closing' ? '视频处理已收尾 ' : '视频处理进度 ') + pct + '%' },
        h('div', { 'data-vp-live-main': '' },
          h('span', { 'data-vp-live-icon': '' },
            h('svg', { viewBox: '0 0 64 64', 'aria-hidden': 'true' },
              h('circle', { cx: 32, cy: 32, r: ringR, 'data-vp-live-ring-track': '' }),
              h('circle', {
                cx: 32, cy: 32, r: ringR, 'data-vp-live-ring-value': '',
                style: { strokeDasharray: ringC, strokeDashoffset: ringOffset },
              })
            ),
            liveCover
              ? h('img', { 'data-vp-live-cover': '', src: liveCover, alt: '', referrerPolicy: 'no-referrer', onError: (e) => { try { if (e.currentTarget.src !== COVER_FALLBACK) e.currentTarget.src = COVER_FALLBACK } catch {} } })
              : h('span', { 'data-vp-live-cover': '', 'data-vp-live-cover-empty': '' },
                h('svg', { viewBox: '0 0 24 24', 'data-vp-live-play': '', 'aria-hidden': 'true' },
                  h('path', { d: 'M8 5.14v13.72L19 12 8 5.14Z' }))),
            live.phase === 'ready' || live.phase === 'error'
              || live.phase === 'canceled' || live.phase === 'cancelled'
              ? h('span', { 'data-vp-live-badge': '', 'data-kind': live.phase },
                h('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' },
                  live.phase === 'ready'
                    ? h('path', { d: 'M20 6 9 17l-5-5' })
                    : [h('path', { key: 'line', d: 'M12 7v6' }), h('path', { key: 'dot', d: 'M12 17h.01' })]))
              : null
          ),
          h('div', { 'data-vp-live-body': '' },
            h('div', { 'data-vp-live-title': '', title: live.title || '' }, live.title || '正在读取视频'),
            h('div', { 'data-vp-live-sub': '' }, sub),
            metaLine(live) ? h('div', { 'data-vp-live-meta': '' }, metaLine(live)) : null
          )
        )
      )
    }

    // Publish one running batch row into the processing card. The queue is the only
    // writer for shortlist jobs (there is no JobCard for them), so this is what makes
    // the ring/ETA/focus appear for a search-driven run.
    function publishQueueLive(sessionId, job, createdAt, fresh) {
      if (!sessionId || !job || !job.job_id) return
      const overview = job.overview || null
        const state = String(job.state || 'running')
        const phase = state === 'failed' ? 'error'
        : state === 'ready' ? 'ready'
          : (state === 'canceled' || state === 'cancelled') ? 'canceled'
            : 'running'
      const raw = job.progress
      const pct = phase === 'ready'
        ? 100
        : raw === null || raw === undefined
          ? 0
          : Math.round(Math.max(0, Math.min(1, Number(raw))) * 100)
      publishLive({
        sessionId,
        origin: 'batch',
        jobId: String(job.job_id),
        videoId: job.video_id || (overview && overview.video_id) || '',
        title: (overview && overview.title) || job.title || '',
        uploader: (overview && overview.uploader) || job.uploader || '',
        views: Number(job.views) || 0,
        coverUrl: (overview && overview.cover_url) || job.cover_url || '',
        duration: (overview && overview.duration) || (job.duration_ms ? fmtTime(job.duration_ms) : undefined),
        durationMs: job.duration_ms,
        positionMs: job.position_ms,
        phase,
        pct,
        stage: phase === 'ready' ? '已完成' : (state === 'canceled' || state === 'cancelled') ? '已取消' : phase === 'error' ? '遇到问题' : friendlyStage(job.stage),
        errorMessage: phase === 'error' ? ((state === 'canceled' || state === 'cancelled') ? '已取消' : (job.error_message || '视频处理失败')) : undefined,
        remedy: phase === 'error' ? job.remedy : undefined,
        transcript: overview && overview.metrics ? overview.metrics.transcript_source : undefined,
        transcriptAvailable: overview && overview.capabilities ? overview.capabilities.transcript : undefined,
        captionKind: overview && overview.metrics && overview.metrics.caption_track ? overview.metrics.caption_track.kind : undefined,
        ocrState: overview && overview.capabilities ? overview.capabilities.ocr_state : undefined,
        visualIndexState: overview && overview.visual_index ? overview.visual_index.state : undefined,
        visualRead: overview && overview.visual_index ? overview.visual_index.read_frames : undefined,
        visualTotal: overview && overview.visual_index ? overview.visual_index.total_frames : undefined,
        visualRemaining: overview && overview.visual_index ? overview.visual_index.remaining_frames : undefined,
        createdAt: createdAt ? new Date(createdAt).toISOString() : new Date().toISOString(),
        clearFocus: fresh === true,
      })
    }

    // Multi-video runs keep one compact row per job. The first job also has the
    // full LiveStrip card; this strip makes the other jobs (and their failures)
    // visible instead of leaving them silent in the queue.
    function QueueStrip(props) {
      const sid = sessionKey(props)
      const sessionRunning = !!(props && props.session && props.session.running)
        || (typeof window !== 'undefined' && window.__VIDEO2AGENT_DEBUG__ === true && window.__VIDEO2AGENT_TEST_RUNNING__ === true)
      const queue = useQueue(sid)
      const [status, setStatus] = React.useState({})
      const [canceling, setCanceling] = React.useState({})
      const [dismissed, setDismissed] = React.useState(false)
      const [stopError, setStopError] = React.useState('')
      // A queue loaded from storage is history until the first poll proves a
      // row is still running. Rendering it immediately was the ghost card on
      // switching back to a conversation whose jobs had already finished.
      const [hydrated, setHydrated] = React.useState(() => !queueFor(sid))
      const [hydratedSid, setHydratedSid] = React.useState(sid)
      const firstPoll = React.useRef(true)
      React.useEffect(() => {
        firstPoll.current = true
        const q = queueFor(sid)
        setStatus({})
        setHydratedSid(sid)
        setHydrated(!q)
      }, [sid])
      // PTC sessions invoke the tool through run_code, so no Card mounts and the
      // shortlist result never reaches this component. The Host persists the
      // started rows per session; this poll is the dock's bridge for that path.
      React.useEffect(() => {
        if (!sid) return undefined
        let alive = true
        let timer = null
        const pull = async () => {
          try {
            const response = await fetch('/api/video2agent/queue?session=' + encodeURIComponent(sid))
            const data = await response.json().catch(() => ({}))
            if (!alive || !data || data.ok !== true || !data.queue || !Array.isArray(data.queue.jobs)) return
            const snap = data.queue
            const startedAt = Number(snap.started_at) || 0
            if (!snap.jobs.length) return
            const current = queueFor(sid)
            const keyOf = (job) => String((job && (job.job_id || job.video_id || job.source)) || '')
            const currentIds = new Set(((current && current.jobs) || []).map(keyOf).filter(Boolean))
            // Only a batch that is still working may extend a newer table. A
            // finished batch must never be resurrected over a later single row:
            // that is the "cleared, then the old batch came back" report.
            const snapLive = snap.jobs.some((job) => job && (job.state === 'running' || job.state === 'queued' || !job.job_id))
            if (current && current.createdAt && startedAt && current.createdAt >= startedAt) {
              if (!snapLive) return
              // A newer single row (a direct ingest the model started later) must
              // not hide the batch: the Host snapshot is the multi-row record.
              // Without this the table stayed at one row while nine videos ran.
              // Skip a row we already show for the same video: a retried
              // ingest gets a new job id, and matching only on job_id let the
              // snapshot add a twin row for the same video.
              const currentVideos = new Set(((current && current.jobs) || [])
                .map((row) => (row && row.video_id ? String(row.video_id) : ''))
                .filter(Boolean))
              const currentSources = new Set(((current && current.jobs) || [])
                .map((row) => (row && row.source ? resolveUrlKey(row.source) : ''))
                .filter(Boolean))
              const extra = snap.jobs.filter((job) => {
                const id = keyOf(job)
                if (!id || currentIds.has(id)) return false
                if (job.video_id && currentVideos.has(String(job.video_id))) return false
                if (job.source && currentSources.has(resolveUrlKey(job.source))) return false
                return true
              })
              if (!extra.length) return
              // A merged-in live row means the table is no longer finished: keep
              // the old finishedAt and the completion timer fires immediately when
              // the merged rows finish, so the table vanishes without the 8s hold.
              const { finishedAt, ...rest } = current
              const seenMerged = (current.seenJobIds || []).slice()
              for (const row of extra) {
                const id = String((row && row.job_id) || '')
                if (id && !seenMerged.includes(id)) seenMerged.push(id)
              }
              storeQueue(sid, {
                ...rest,
                batchId: current.batchId || snap.batch_id || undefined,
                campaignId: current.campaignId || snap.campaign_id || undefined,
                jobs: [...(current.jobs || []), ...extra],
                seenJobIds: seenMerged.slice(-50),
              })
              return
            }
            const clearedAt = queueClearedAt(sid)
            if (!current && clearedAt && startedAt && startedAt <= clearedAt) return
            // A long-running video (67min) outlives the 5-minute window; keep
            // adopting the Host queue while any row is still live.
            if (!current && startedAt && !snapLive && Date.now() - startedAt > 5 * 60 * 1000) return
            storeQueue(sid, {
              createdAt: startedAt || Date.now(),
              batchId: snap.batch_id || undefined,
              campaignId: snap.campaign_id || undefined,
              jobs: snap.jobs,
              // The snapshot's jobs are history from now on: a remount of one of
              // their cards must only refresh, never append a second row.
              seenJobIds: snap.jobs.map((job) => String((job && job.job_id) || '')).filter(Boolean).slice(-50),
              collapsed: false,
              evidence: null,
            })
            const first = snap.jobs.find((job) => job && job.primary && job.job_id) || snap.jobs.find((job) => job && job.job_id)
            if (first && first.job_id) {
              publishLive({
                sessionId: sid,
                origin: 'batch',
                jobId: String(first.job_id),
                videoId: first.video_id || '',
                title: first.title || '',
                coverUrl: first.cover_url || '',
                duration: first.duration_ms ? fmtTime(first.duration_ms) : undefined,
                phase: 'running',
                pct: 0,
                stage: '已经启动，正在准备',
                createdAt: new Date().toISOString(),
              })
            }
          } catch {}
        }
        // Recursive setTimeout: the hidden delay is re-read every tick, so a tab
        // hidden at mount and later visible speeds up again (an interval froze
        // whatever value was true at mount).
        const loop = async () => {
          if (!alive) return
          await pull()
          if (!alive) return
          timer = setTimeout(loop, typeof document !== 'undefined' && document.hidden ? 10000 : 2500)
        }
        loop()
        return () => { alive = false; if (timer) clearTimeout(timer) }
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [sid])
      // A turn that starts after an old batch must not inherit its rows. Keep
      // the queue only if this session's live card points at one of its jobs.
      const turnRef = React.useRef(false)
      React.useEffect(() => {
        if (!sessionRunning) { turnRef.current = false; return }
        if (turnRef.current) return
        turnRef.current = true
        const q = queueFor(sid)
        if (!q) return
        const live = liveFor(sid)
        const activeJobId = live && live.phase === 'running' ? live.jobId : null
        const keep = activeJobId && Array.isArray(q.jobs) && q.jobs.some((job) => String(job.job_id) === String(activeJobId))
        const stillRunning = Array.isArray(q.jobs) && q.jobs.some((job) => job
          && !['ready', 'failed', 'canceled', 'cancelled'].includes(String(job.state)))
        // Never clear a running batch just because the live card points at a
        // different job; that made the table disappear and the single LiveStrip
        // reappear. Only old, fully-terminal history is removable here.
        // Use the same clear as the 清除 button: a bare storeQueue(null) left the
        // batch's last live entry alive, so a completion card replayed over the
        // empty table.
        if (!keep && !stillRunning && Date.now() - Number(q.createdAt || 0) > 5000) clearBatch(sid)
      }, [sessionRunning, sid])
      // useQueue can hydrate after the first render (null -> stored queue).
      // Keep an old queue hidden until the poll decides whether it is alive.
      React.useEffect(() => {
        const q = queue
        if (!q) return
        if (firstPoll.current) setHydrated(false)
      }, [queue && queue.createdAt, queue && queue.jobs.length])
      const jobs = queue && Array.isArray(queue.jobs) ? queue.jobs : []
      const jobsKey = jobs.map((job) => String((job && job.job_id) || job.video_id || '')).join('|')
      // A campaign starts later waves on the Host. Without this poll the table
      // would keep showing only the first wave and the queued rows would never
      // receive their job ids.
      React.useEffect(() => {
        const campaignId = queue && queue.campaignId
        if (!campaignId) return undefined
        // Mounting a restored, already-finished table must not POST a tick: the
        // poll starts the next wave, which would run for a dead batch.
        const status = queue && queue.campaignStatus
        if (status === 'complete' || status === 'failed') return undefined
        let alive = true
        let timer = null
        const tick = async () => {
          try {
            const response = await fetch('/api/video2agent/campaign?id=' + encodeURIComponent(campaignId), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: '{}',
            })
            const data = await response.json().catch(() => ({}))
            if (!alive) return
            if (!data || data.ok !== true || !Array.isArray(data.items)) {
              // A transient 500 must not permanently stop later waves.
              timer = setTimeout(tick, 4000)
              return
            }
            const current = queueFor(sid)
            if (!current || current.campaignId !== campaignId) return
            const byVideo = new Map((current.jobs || []).map((job) => [String(job.video_id || ''), { ...job }]))
            for (const item of data.items) {
              const key = String(item.video_id || '')
              if (!key) continue
              const prev = byVideo.get(key) || {}
              // Campaign rows carry '' / 0 for metadata they do not know; do not
              // let that wipe a title/cover already filled by resolve/overview.
              byVideo.set(key, {
                ...prev,
                ...item,
                title: item.title || prev.title,
                cover_url: item.cover_url || prev.cover_url,
                uploader: item.uploader || prev.uploader,
                duration_ms: item.duration_ms || prev.duration_ms,
                error_message: item.error_message || prev.error_message,
                origin: 'shortlist',
                state: item.state || prev.state || 'queued',
              })
            }
            const nextJobs = Array.from(byVideo.values())
            const nextStatus = data.status || current.campaignStatus
            // Persist a status-only change too: otherwise a table restored later
            // re-arms the poll against a campaign that already finished.
            if (JSON.stringify(nextJobs) !== JSON.stringify(current.jobs || [])
              || nextStatus !== current.campaignStatus) {
              storeQueue(sid, { ...current, jobs: nextJobs, campaignStatus: nextStatus })
            }
            if (data.status !== 'complete' && data.status !== 'failed') timer = setTimeout(tick, 2500)
          } catch {
            if (alive) timer = setTimeout(tick, 4000)
          }
        }
        tick()
        return () => { alive = false; if (timer) clearTimeout(timer) }
      }, [sid, queue && queue.campaignId])
      // Both spellings: Python writes canceled, but a legacy sidecar may say cancelled.
      const terminal = (state) => state === 'ready' || state === 'failed'
        || state === 'canceled' || state === 'cancelled'
      const rowKey = (job) => String((job && (job.job_id || job.video_id || job.source)) || '')
      const rows = jobs.map((job) => ({ ...job, ...(status[job.job_id] || {}) }))
      const pendingQueued = rows.some((job) => job.state === 'queued' || (!job.job_id && !terminal(job.state)))
      const anyRunning = pendingQueued || rows.some((job) => job.job_id && !terminal(job.state))
      const allTerminal = rows.length > 0 && !anyRunning
      const done = rows.filter((job) => terminal(job.state)).length
      const ok = rows.filter((job) => job.state === 'ready').length
      const failed = rows.filter((job) => job.state === 'failed').length
      const canceled = rows.filter((job) => job.state === 'canceled' || job.state === 'cancelled').length
      const running = rows.filter((job) => !terminal(job.state)).length
      const coverFor = (job) => {
        if (!job) return ''
        // cover_url is an image URL; `source` is a page URL or a local path, so
        // sending it to the proxy only produced a 400 in the console.
        const image = String(job.cover_url || '')
        if (!/^https?:\/\//i.test(image)) return ''
        return coverThrough(image)
      }
      // A row can exist before its title/cover resolve. Fill them in by BVID
      // instead of showing a bare BV id or an empty cover.
      React.useEffect(() => {
        const missing = jobs.filter((job) => job
          && (!job.title || /^BV[0-9A-Za-z]{10}$|^av\d+$/i.test(String(job.title)) || !job.cover_url)
          && (/^https?:/i.test(String(job.source || '')) || /^BV/i.test(String(job.video_id || ''))))
        if (!missing.length) return undefined
        let alive = true
        ;(async () => {
          const found = {}
          await Promise.all(missing.map(async (job) => {
            try {
              const url = job.source && /^https?:/i.test(job.source)
                ? job.source
                : 'https://www.bilibili.com/video/' + job.video_id
              const response = await fetch('/api/video2agent/resolve?url=' + encodeURIComponent(url))
              const data = await response.json().catch(() => ({}))
              if (data && data.title) {
                const key = job.job_id || job.video_id
                found[key] = { title: data.title, cover_url: data.cover_url || '', uploader: data.uploader || '', duration_ms: data.duration_ms || job.duration_ms }
              }
            } catch {}
          }))
          if (!alive) return
          const current = queueFor(sid)
          if (!current || !Array.isArray(current.jobs)) return
          const next = current.jobs.map((job) => {
            const key = job.job_id || job.video_id
            return found[key] ? { ...job, ...found[key] } : job
          })
          storeQueue(sid, { ...current, jobs: next })
        })()
        return () => { alive = false }
      }, [jobsKey, sid])

      // One poll for the whole batch. It stops itself as soon as every row is
      // terminal; a 404 is retried three times and then becomes a visible failed
      // row instead of polling (and spawning Python) forever.
      React.useEffect(() => {
        if (!jobs.length || !anyRunning || !jobs.some((job) => job && job.job_id)) return undefined
        let alive = true
        let timer = null
        let stopped = false
        let ticking = false
        const misses = {}
        const tick = async () => {
          const next = {}
          await Promise.all(jobs.map(async (job) => {
            if (!job || !job.job_id) return
            try {
              const response = await fetch('/api/video2agent/job?id=' + encodeURIComponent(job.job_id) + '&overview=0')
              if (!response.ok) {
                if (response.status !== 404) {
                  // A 500 is not "the job was deleted": keep the row visible and
                  // let the next poll retry instead of offering a misleading restart.
                  next[job.job_id] = {
                    state: job.state,
                    message: `进度更新失败（HTTP ${response.status}），稍后重试`,
                  }
                  return
                }
                misses[job.job_id] = (misses[job.job_id] || 0) + 1
                if (misses[job.job_id] >= 3) {
                  next[job.job_id] = {
                    state: 'failed',
                    lost: true,
                    error_message: '任务已不存在（无法读取进度）',
                    remedy: '重新开始这个视频',
                  }
                }
                return
              }
              misses[job.job_id] = 0
              const data = await response.json()
              const live = data && data.job
              if (!live) return
              next[job.job_id] = {
                state: live.state || job.state,
                stage: live.stage || job.stage,
                message: live.message || job.message,
                progress: live.progress,
                position_ms: live.position_ms,
                duration_ms: live.duration_ms || job.duration_ms,
                video_id: live.video_id || job.video_id,
                error_message: live.error_message || live.errorMessage || job.error_message,
                remedy: live.remedy || job.remedy,
                overview: job.overview || null,
              }
            } catch {}
          }))
          if (!alive) return
          setStatus((current) => ({ ...current, ...next }))
          // Persist a terminal state so a reload shows the finished record
          // immediately instead of replaying "进行中" for every old row.
          if (Object.keys(next).some((id) => next[id] && terminal(next[id].state))) {
            const currentQueue = queueFor(sid)
            if (currentQueue && Array.isArray(currentQueue.jobs)) {
              const persisted = currentQueue.jobs.map((job) => ({ ...job, ...(next[job.job_id] || {}) }))
              if (JSON.stringify(persisted) !== JSON.stringify(currentQueue.jobs)) {
                storeQueue(sid, { ...currentQueue, jobs: persisted })
              }
            }
          }
          const merged = jobs.map((job) => ({ ...job, ...(next[job.job_id] || {}) }))
          if (firstPoll.current) {
            firstPoll.current = false
            const stillRunning = merged.some((job) => job && job.job_id && !terminal(job.state))
            setHydrated(true)
            if (!stillRunning) {
              stopped = true
              if (timer) { clearInterval(timer); timer = null }
              clearBatch(sid)
              return
            }
          }
          const active = merged.find((job) => job.primary && job.job_id && !job.lost && !terminal(job.state))
            || merged.find((job) => job.origin === 'shortlist' && job.job_id && !job.lost && !terminal(job.state))
            || merged.find((job) => job.job_id && !job.lost && !terminal(job.state))
          if (active) {
            const fresh = LAST_BATCH_LIVE.get(sid) !== active.job_id
            LAST_BATCH_LIVE.set(sid, active.job_id)
            publishQueueLive(sid, active, queue && queue.createdAt, fresh)
          }
          const stillRunning = jobs.some((job) => {
            const state = (next[job.job_id] && next[job.job_id].state) || job.state
            return !terminal(state)
          })
          if (!stillRunning) {
            stopped = true
            if (timer) { clearInterval(timer); timer = null }
            const finalRow = merged.find((job) => job.primary && job.job_id && terminal(job.state))
              || merged.slice().reverse().find((job) => job.job_id && terminal(job.state))
            if (finalRow) {
              LAST_BATCH_LIVE.set(sid, finalRow.job_id)
              publishQueueLive(sid, finalRow, queue && queue.createdAt, false)
            }
          }
        }
        tick()
        timer = setInterval(() => {
          // A slow tick must not stack requests: each one spawns Python.
          if (!stopped && !ticking) {
            ticking = true
            Promise.resolve(tick()).finally(() => { ticking = false })
          }
        }, 2500)
        return () => { alive = false; stopped = true; if (timer) clearInterval(timer) }
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [queue && queue.createdAt, jobsKey, anyRunning])

      React.useEffect(() => {
        if (!stopError) return undefined
        const timer = setTimeout(() => setStopError(''), 2200)
        return () => clearTimeout(timer)
      }, [stopError])

      // A completed batch collapses to a compact receipt instead of vanishing.
      // The old 2.6s clear made the completion card flash and then let a stale
      // LiveStrip replay the same job when a conversation was reopened.
      React.useEffect(() => {
        // Hold the completed table long enough to read, then clear it. A
        // terminal queue restored from storage is stale: clear it without
        // replaying a completion card on a conversation switch.
        if (!allTerminal || (queue && queue.collapsed)) {
          setDismissed(false)
          return undefined
        }
        if (!Object.keys(status).length) {
          clearBatch(sid)
          return undefined
        }
        const finishedAt = Number(queue && queue.finishedAt || 0)
        if (!finishedAt) {
          storeQueue(sid, { ...queue, finishedAt: Date.now() })
          return undefined
        }
        const remaining = Math.max(0, 8000 - (Date.now() - finishedAt))
        if (remaining <= 0) { clearBatch(sid); return undefined }
        const timer = setTimeout(() => clearBatch(sid), remaining)
        return () => clearTimeout(timer)
      }, [allTerminal, jobsKey, sid, queue && queue.createdAt, queue && queue.finishedAt, status])

      // '显示处理卡片' must hide the batch table too, not only the single card.
      // Subscribe so toggling it updates an already-mounted table.
      const settings = useSettings()
      if (!settings.enabled) return null
      // A terminal queue restored from storage is history, not a new completion.
      // Do not paint it for one frame before the effect clears it.
      const restoredTerminal = allTerminal && !Object.keys(status).length
      const freshTerminal = allTerminal && Object.keys(status).length > 0
      if (hydratedSid !== sid || !hydrated) return null
      // A turn ending must not hide a batch that is still running in the
      // background. Only a terminal history record waits for its fade/clear.
      if (!sessionRunning && !freshTerminal && !anyRunning) return null
      if (!rows.length || dismissed || restoredTerminal) return null

      if (queue && queue.collapsed) {
        // The pill must show the row that is actually being worked on, not the
        // primary: after a dedupe the primary can already be finished while the
        // last row still runs, and the pill showed the wrong cover.
        const activeRow = rows.find((job) => job && !terminal(job.state))
        const top = activeRow || rows.find((job) => job.primary) || rows[0]
        const topCover = coverFor(top)
        const label = allTerminal ? (failed ? '未完成' : canceled ? '已取消' : '已完成') : '正在处理'
        return h('div', { 'data-vp-queue': '', 'data-vp-queue-collapsed': '', 'data-vp-queue-pill-job': String(top && top.job_id || ''), 'data-terminal': allTerminal ? 'true' : undefined },
          h('button', {
            type: 'button',
            'data-vp-queue-expand': '',
            'aria-label': allTerminal ? '展开完成记录' : '展开已选视频表',
            onClick: () => storeQueue(sid, { ...queue, collapsed: false }),
          },
          topCover
            ? h('img', {
              'data-vp-queue-pill-cover': '', src: topCover, alt: '',
              onError: (e) => { try { if (e.currentTarget.src !== COVER_FALLBACK) e.currentTarget.src = COVER_FALLBACK } catch {} },
            })
            : h('span', { 'data-vp-queue-pill-dot': '' }),
          h('b', {}, label),
          h('span', { 'data-vp-queue-pill-action': '' }, '展开'),
          h('span', { 'data-vp-queue-pill-caret': '', 'aria-hidden': 'true' }, '⌄')))
      }

      const cancel = async (job) => {
        const key = rowKey(job)
        if (!job || !job.job_id || canceling[key]) return
        setStopError('')
        setCanceling((current) => ({ ...current, [key]: true }))
        try {
          const response = await fetch('/api/video2agent/jobs/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: job.job_id }),
          })
          if (!response.ok) {
            // 409 means the job already finished: stopping it is a no-op, not a
            // failed stop ("停止失败" for a completed row was confusing).
            if (response.status !== 409) setStopError('停止失败')
            setCanceling((current) => { const next = { ...current }; delete next[key]; return next })
            return
          }
          setStatus((current) => ({ ...current, [job.job_id]: { ...(current[job.job_id] || {}), canceling: true } }))
        } catch {
          setStopError('停止失败')
          setCanceling((current) => { const next = { ...current }; delete next[key]; return next })
        }
      }

      // 取消 is not 完成: a stopped video was never indexed, and a green
      // 已完成 header over a row that says 已取消 is the same lie the rest of
      // this file exists to avoid.
      const headTitle = allTerminal ? (failed ? '未完成' : canceled ? '已取消' : '已完成') : ''
      const headSub = ''
      // The progress ring belongs to the row that is actually processing. Picking
      // the first non-terminal row put it on a queued row whenever the running
      // video was not first (campaign waves, a retried row, a queued row without a
      // job id): the table said "正在处理" on row 3 while the ring sat on row 2.
      const isRunning = (job) => job && job.state === 'running' && !!job.job_id
      const runningJob = rows.find((job) => isRunning(job) && job.primary) || rows.find(isRunning)
      const activeJob = runningJob || rows.find((job) => !terminal(job.state))
      const rawProgress = activeJob ? Number(activeJob.progress) : 0
      const activeProgress = Number.isFinite(rawProgress)
        ? Math.max(0.08, Math.min(1, rawProgress > 1 ? rawProgress / 100 : rawProgress))
        : 0.08
      return h('div', { 'data-vp-queue': '', role: 'region', 'aria-label': '已选视频处理进度', 'aria-live': 'polite' },
        h('div', { 'data-vp-queue-head': '' },
          headTitle ? h('b', {}, headTitle) : null,
          headSub ? h('span', { 'data-vp-queue-sub': '' }, headSub) : null,
          stopError ? h('span', { 'data-vp-queue-stop-error': '' }, stopError) : null,
          h('button', {
            type: 'button',
            'data-vp-queue-collapse': '',
            'aria-label': allTerminal ? '收起完成记录' : '收起已选视频表',
            onClick: () => storeQueue(sid, { ...queue, collapsed: true }),
          }, '收起'),
          allTerminal
            ? h('button', {
              type: 'button',
              'data-vp-queue-clear': '',
              'aria-label': '清除完成记录',
              title: '清除记录',
              onClick: () => clearBatch(sid),
            }, '清除')
            : null
        ),
        h('div', { 'data-vp-queue-rows': '' }, rows.map((job) => {
          const state = String(job.state || 'running')
          const key = rowKey(job)
          const isCanceling = !!(canceling[key] || job.canceling)
          // The row is read at a glance, so it uses the same plain-language stage
          // as the live card. Raw slugs (`ocr`, `sampling`, `transcribing`) are
          // implementation detail and never belong above the composer.
          const label = state === 'ready' ? '已完成'
            : state === 'failed' ? '未完成'
              : (state === 'canceled' || state === 'cancelled') ? '已取消'
                : state === 'queued' ? '排队中'
                  : isCanceling ? '取消中'
                    : '正在处理'
          const tone = state === 'ready' ? 'ok'
        : state === 'failed' || state === 'canceled' || state === 'cancelled' || state === 'queued' ? 'muted' : 'run'
          const cover = coverFor(job)
          // Never use a raw BV/av/vid id as the title. A row created before
          // resolve says 视频; the resolve effect replaces it with the real title.
          const displayTitle = displayTitleFor(job)
          const isActive = !!activeJob && key === rowKey(activeJob)
          const coverNode = cover
            ? h('img', {
              'data-vp-queue-cover': '', 'data-active': isActive ? 'on' : undefined,
              src: cover, loading: 'lazy', alt: '',
              onError: (e) => { try { if (e.currentTarget.src !== COVER_FALLBACK) e.currentTarget.src = COVER_FALLBACK } catch {} },
            })
            : h('div', {
              'data-vp-queue-cover': '', 'data-empty': 'on',
              'data-active': isActive ? 'on' : undefined,
            }, '▶')
          const coverCell = isActive
            ? h('span', { 'data-vp-queue-ring-wrap': '' },
              h('svg', { viewBox: '0 0 108 66', 'data-vp-queue-ring': '', 'aria-hidden': 'true' },
                h('rect', { 'data-vp-queue-ring-track': '', x: 4, y: 4, width: 100, height: 58, rx: 10, pathLength: 100 }),
                h('rect', {
                  'data-vp-queue-ring-value': '', x: 4, y: 4, width: 100, height: 58, rx: 10, pathLength: 100,
                  style: { strokeDasharray: 100, strokeDashoffset: 100 * (1 - activeProgress) },
                })),
              coverNode)
            : coverNode
          return h('div', {
            'data-vp-queue-row': '',
            'data-state': tone,
            title: displayTitle,
            key,
          },
          coverCell,
          h('div', { 'data-vp-queue-main': '' },
            h('div', { 'data-vp-queue-titleline': '' },
              h('span', { 'data-vp-queue-name': '', title: displayTitle }, displayTitle)),
            metaLine(job) ? h('div', { 'data-vp-queue-meta': '' }, metaLine(job)) : null,
          ),
          h('span', { 'data-vp-queue-tail': '' },
            h('span', { 'data-vp-queue-state': '' }, label),
            // A campaign's queued row has no job_id yet; cancel() would return
            // silently, so the button must not render at all.
            terminal(state) || !job.job_id
              ? null
              : h('button', {
                type: 'button',
                'data-vp-queue-cancel': '',
                'aria-label': (isCanceling ? '取消中：' : '停止：') + displayTitle,
                title: isCanceling ? '取消中' : '停止',
                disabled: isCanceling,
                onClick: () => cancel(job),
              }, isCanceling ? '取消中' : '停止'))
          )
        }))
      )
    }

    const HIDDEN_SEARCH_BY_SESSION = new Map()
    // The only discovery surface left. The old candidate picker is gone: the
    // Host starts the model's shortlist and the table shows the jobs. This card
    // only says what the search is doing, in the same glass shell as before.
    function SearchStatus(props) {
      const sid = sessionKey(props)
      const running = !!(props && props.session && props.session.running)
      const queue = useQueue(sid)
      const [status, setStatus] = React.useState(null)
      const holdRef = React.useRef(null)
      const settings = useSettings()
      React.useEffect(() => {
        if (!settings.enabled) return undefined
        let alive = true
        let timer = null
        let lastPhase = null
        const poll = async () => {
          if (!alive) return
          const hidden = typeof document !== 'undefined' && document.hidden === true
          try {
            const url = '/api/video2agent/discovery/status' + (sid ? '?session=' + encodeURIComponent(sid) : '')
            const response = await fetch(url)
            const data = await response.json()
            const next = data && data.status ? data.status : null
            // A find-only turn ends with "curating" and no shortlist. That card is
            // model input, not a result: drop it as soon as the turn ends instead
            // of leaving a spinner until the Host's status expires. Remember the
            // hidden status so the next turn cannot resurrect the same card; a
            // newer find has a newer at and shows normally.
            const findOnly = !!next && (next.phase === 'searching' || next.phase === 'curating')
            const hiddenAt = Number(HIDDEN_SEARCH_BY_SESSION.get(sid) || 0)
            const hiddenStatus = findOnly && Number((next && next.at) || 0) <= hiddenAt
            const dropFindOnly = findOnly && (!running || hiddenStatus)
            const firstHide = findOnly && !running && !hiddenStatus
            if (firstHide && next) {
              HIDDEN_SEARCH_BY_SESSION.set(sid, Number(next.at || 0) || Date.now())
              // Clear the Host status as well: the in-page latch covers this tab,
              // but a reload or a later turn must not read the stale curating
              // line. Fire-and-forget; the card is already hidden.
              try {
                fetch('/api/video2agent/discovery/clear', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ session: sid }),
                }).catch(() => {})
              } catch {}
            }
            lastPhase = dropFindOnly ? null : next && next.phase
            if (alive) {
              if (dropFindOnly) {
                if (holdRef.current) { clearTimeout(holdRef.current); holdRef.current = null }
                setStatus(null)
              } else if (next) {
                if (holdRef.current) { clearTimeout(holdRef.current); holdRef.current = null }
                setStatus(next)
              } else if (!holdRef.current) {
                // A shortlist clears the status before the batch table paints.
                // Hold the last search card briefly so it does not blink out and
                // immediately come back as a new card.
                holdRef.current = setTimeout(() => {
                  holdRef.current = null
                  setStatus(null)
                }, 6000)
              }
            }
          } catch {}
          if (alive) {
            const busy = lastPhase === 'searching' || lastPhase === 'curating' || lastPhase === 'starting'
            const delay = hidden ? 8000 : busy ? 2500 : running ? 2500 : 10000
            timer = setTimeout(poll, delay)
          }
        }
        poll()
        return () => {
          alive = false
          if (timer) clearTimeout(timer)
          if (holdRef.current) { clearTimeout(holdRef.current); holdRef.current = null }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [sid, running, settings.enabled])
      const jobs = queue && Array.isArray(queue.jobs) ? queue.jobs : []
      if (jobs.length) return null
      const phase = status && status.phase
      if (!status) return null
      if (phase === 'error' && (status.kind === 'start' || status.kind === 'selection')) return null
      if (!['searching', 'curating', 'starting', 'empty', 'error'].includes(phase)) return null
      const title = phase === 'searching'
        ? '正在找视频'
        : phase === 'curating'
          ? '正在筛选'
          : phase === 'starting'
            ? '正在准备'
            : phase === 'empty'
              ? '没有找到候选'
              : '搜索失败'
      const note = phase === 'searching'
        ? '正在搜索：' + String(status.query || '视频')
        : phase === 'curating'
          ? '正在按标题、播放量、日期筛选…'
          : phase === 'starting'
            ? '视频已选定，正在开始处理…'
            : phase === 'empty'
              ? '换一个更具体的关键词再试。'
              : String(status.error || '搜索没有完成，请重试。')
      const candidates = Array.isArray(status.candidates) ? status.candidates.slice(0, 4) : []
      const busy = phase === 'searching' || phase === 'curating' || phase === 'starting'
      return h('div', {
        'data-vp-search': phase,
        role: 'status',
        'aria-live': 'polite',
      },
      h('div', { 'data-vp-search-head': '' },
        h('span', { 'data-vp-search-title': '' }, title)),
      h('div', { 'data-vp-search-line': '' },
        busy ? h('span', { 'data-vp-search-dots': '', 'aria-hidden': 'true' },
          h('i', { key: 'a' }), h('i', { key: 'b' }), h('i', { key: 'c' })) : null,
        h('span', {}, note)),
      candidates.length ? h('div', { 'data-vp-search-list': '' }, candidates.map((c, i) => h('div', { 'data-vp-search-item': '', key: c.video_id || i },
        c.cover_url
          ? h('img', { 'data-vp-search-cover': '', src: coverThrough(c.cover_url), alt: '', onError: (e) => { try { if (e.currentTarget.src !== COVER_FALLBACK) e.currentTarget.src = COVER_FALLBACK } catch {} } })
          : h('span', { 'data-vp-search-cover': '', 'data-empty': 'on' }, '▶'),
        h('div', { 'data-vp-search-body': '' },
          h('div', { 'data-vp-search-name': '', title: c.title || '' }, c.title || '视频'),
          metaLine(c) ? h('div', { 'data-vp-search-meta': '' }, metaLine(c)) : null)
      ))) : null)
    }

    function LinkPreview(props) {
      // Hook order must stay constant: read the switch, run every hook, and only
      // then decide whether to render (an early return here changes the hook
      // count between enabled states and crashes React).
      const settings = useSettings()
      const draft = String(props && props.input && props.input.draft || '')
      const link = detectVideoLink(draft)
      const url = link ? link.url : ''
      // While a job runs, the dock already carries a tall progress card: shrink this
      // preview to one line. The compact state is derived from the live entry, not
      // remembered, so it restores itself the moment the job finishes.
      const live = useLive(sessionKey(props))
      const jobActive = !!(live && !live.hidden && (live.phase === 'running' || live.phase === 'closing'))
      const compact = jobActive && !!url
      const cached = url && Date.now() - (RESOLVE_CACHE_TS.get(url) || 0) <= getSettings().cacheTtlMs ? RESOLVE_CACHE.get(url) : null
      const [state, setState] = React.useState(cached ? { phase: 'ready', data: cached } : { phase: 'idle', data: null })
      React.useEffect(() => {
        if (!url) { setState({ phase: 'idle', data: null }); return undefined }
        const hit = RESOLVE_CACHE.get(url)
        if (hit && Date.now() - (RESOLVE_CACHE_TS.get(url) || 0) <= getSettings().cacheTtlMs) { setState({ phase: 'ready', data: hit }); return undefined }
        if (hit) { RESOLVE_CACHE.delete(url); RESOLVE_CACHE_TS.delete(url) }
        let alive = true
        setState({ phase: 'loading', data: null })
        const controller = typeof AbortController === 'function' ? new AbortController() : null
        const timer = setTimeout(() => {
          fetch('/api/video2agent/resolve?url=' + encodeURIComponent(url), controller ? { signal: controller.signal } : undefined)
            .then(async (r) => {
              const data = await r.json().catch(() => ({}))
              if (!r.ok || (data && data.error)) throw new Error('resolve failed')
              return data
            })
            .then((data) => {
              if (!alive) return
              if (data && data.title) {
                RESOLVE_CACHE.set(url, data)
                RESOLVE_CACHE_TS.set(url, Date.now())
                if (RESOLVE_CACHE.size > 24) {
                  const oldest = RESOLVE_CACHE.keys().next().value
                  RESOLVE_CACHE.delete(oldest)
                  RESOLVE_CACHE_TS.delete(oldest)
                }
                persistResolveCache()
              }
              setState({ phase: 'ready', data })
            })
            .catch(() => { if (alive) setState({ phase: 'failed', data: null }) })
        }, 220)
        return () => { alive = false; clearTimeout(timer); if (controller) controller.abort() }
      }, [url])
      if (!settings.enabled) return null
      if (!url) return null
      const data = state.data || {}
      if (state.phase === 'failed') {
        return h('div', { 'data-vp-preview': '' },
          h('div', { 'data-vp-preview-main': '' },
            h('div', { 'data-vp-preview-kicker': '' }, 'B 站视频 · 未能识别'),
            h('div', { 'data-vp-preview-title': '' }, '检查链接，或稍后再试'),
            h('div', { 'data-vp-preview-meta': '' }, h('span', {}, '支持 BV 链接、av 号、b23.tv 短链')))
        )
      }
      const ready = state.phase === 'ready'
      // Compact form: one line under a running progress card. Same element, same data,
      // just fewer rows — so nothing has to be re-fetched when it expands again.
      if (compact) {
        return h('div', { 'data-vp-preview': '', 'data-vp-preview-compact': '' },
          h('div', { 'data-vp-preview-shot': '' },
            ready && data.cover_url
              ? h('img', { 'data-vp-preview-cover': '', src: coverThrough(data.cover_url), alt: '' })
              : h('div', { 'data-vp-preview-cover': '', 'data-empty': 'on' }, '▶'),
            ready && data.duration ? h('span', { 'data-vp-tile-duration': '' }, String(data.duration)) : null
          ),
          h('div', { 'data-vp-preview-main': '' },
            h('div', { 'data-vp-preview-compact-line': '' },
              h('span', { 'data-vp-preview-next': '' }, '下一个'),
              h('span', { 'data-vp-preview-compact-title': '' },
                ready ? (data.title || '视频信息') : '正在读取视频信息…')
            )
          )
        )
      }
      return h('div', { 'data-vp-preview': '' },
        // Same tile language as the discovery cards: cover with the duration in the
        // corner, then title and uploader underneath the kicker.
        h('div', { 'data-vp-preview-shot': '' },
          ready && data.cover_url
            ? h('img', { 'data-vp-preview-cover': '', src: coverThrough(data.cover_url), alt: '' })
            : h('div', { 'data-vp-preview-cover': '', 'data-empty': 'on' }, '▶'),
          ready && data.duration ? h('span', { 'data-vp-tile-duration': '' }, String(data.duration)) : null
        ),
        h('div', { 'data-vp-preview-main': '' },
          h('div', { 'data-vp-preview-kicker': '' }, ready ? 'B 站视频 · 已识别' : 'B 站视频 · 正在识别'),
          h('div', { 'data-vp-preview-title': '' }, ready ? (data.title || '视频信息') : '正在读取视频信息…'),
          h('div', { 'data-vp-preview-meta': '' },
            // The duration already sits on the cover; repeating it here reads as a bug.
            h('span', {}, ready ? (data.uploader || '') : ''),
            ready && data.pubdate ? h('span', {}, String(data.pubdate)) : null
          )
        )
      )
    }

    function LinkCard(props) {
      const data = props.data
      return h('div', { 'data-vp-card': '' },
        h('div', { 'data-vp-head': '' },
          h('div', { 'data-vp-kicker': '' }, 'Bilibili · 视频链接'),
          h('div', { 'data-vp-muted': '' }, data.platform || 'video')
        ),
        h('div', { 'data-vp-linkrow': '' },
          data.cover_url ? h('img', { 'data-vp-cover': '', src: data.cover_url, alt: '', referrerPolicy: 'no-referrer' }) : null,
          h('div', { 'data-vp-linkmain': '' },
            h('div', { 'data-vp-title': '' }, data.title || data.url || '视频'),
            h('div', { 'data-vp-meta': '' },
              h('span', {}, data.uploader || ''),
              h('span', {}, data.duration || ''),
              h('span', {}, '已识别链接')
            ),
            h('div', { 'data-vp-url': '' }, data.url || '')
          )
        ),
        h('div', { 'data-vp-foot': '' },
          h('div', { 'data-vp-muted': '' }, '下一步：建立证据索引'),
          h('div', { 'data-vp-actions': '' },
            h('button', { 'data-vp-btn': 'primary', onClick: () => copyText('分析这个视频：' + String(data.url || '')) }, '复制分析指令')
          )
        )
      )
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        const style = document.createElement('style')
        style.setAttribute('data-plugin-css', 'dsh-video2agent')
        style.textContent = CSS
        document.head.appendChild(style)
        if (typeof ctx.effect === 'function') ctx.effect(() => () => style.remove(), 'dsh-video2agent: styles')

        const slots = (typeof ctx.get === 'function' ? ctx.get('slots') : undefined) || ctx.slots
        if (!slots) return
        // Paint the stored accent before the first card renders, then keep it in
        // sync through the settings listeners.
        applyAccentTheme(getSettings().accentColor)
        startLiveWatchdog()
        if (typeof ctx.effect === 'function') ctx.effect(() => () => stopLiveWatchdog(), 'dsh-video2agent: watchdog')
        hydrateSettings()
        slots.inject('tool.call.toolview', () => slots.register(
          { name: 'tool.call.toolview', key: 'video2agent' },
          Card,
        ))
        if (typeof window !== 'undefined' && window.__VIDEO2AGENT_DEBUG__ === true) {
          window.__video2agentPublishLive = publishLive
          window.__video2agentPublishBatch = (sessionId, jobs) => {
            if (!sessionId || !Array.isArray(jobs) || !jobs.length) return 0
            const rows = jobs.map((job) => ({ ...job, origin: 'shortlist', state: job.state || 'running' }))
            storeQueue(sessionId, { createdAt: Date.now(), jobs: rows, collapsed: false })
            const first = rows.find((job) => job.job_id)
            if (first && first.job_id) {
              publishLive({
                sessionId,
                origin: 'batch',
                jobId: String(first.job_id),
                videoId: first.video_id || '',
                title: first.title || '',
                coverUrl: first.cover_url || '',
                duration: first.duration_ms ? fmtTime(first.duration_ms) : undefined,
                phase: 'running',
                pct: 0,
                stage: '已经启动，正在准备',
                createdAt: new Date().toISOString(),
              })
            }
            return rows.length
          }
          window.__video2agentPublishEvidence = (sessionId, note) => recordEvidence(sessionId, note || null)
          window.__video2agentCanPublishJob = canPublishJob
          window.__video2agentDetectVideoLink = detectVideoLink
          window.__video2agentAccentPalette = accentPalette
          window.__video2agentAccentCss = accentCss
          window.__video2agentShortTimecode = shortTimecode
          window.__video2agentWatchdogTick = watchdogTick
          window.__video2agentCoverThrough = coverThrough
          window.__video2agentDisplayTitle = displayTitleFor
          window.__video2agentResolveState = () => [...RESOLVE_CACHE.entries()]
          window.__video2agentQueueState = (sessionId) => queueFor(sessionId)
          // Test-only: run the real user clear (in-memory map + storage + latch).
          window.__video2agentClearQueue = (sessionId) => clearBatch(sessionId || ACTIVE_SESSION)
          // Test-only: seed a table exactly as the app stores it.
          window.__video2agentSetQueue = (sessionId, value) => storeQueue(sessionId || ACTIVE_SESSION, value)
          window.__video2agentCloseLive = (sessionId) => closeLive(sessionId || ACTIVE_SESSION, liveFor(sessionId || ACTIVE_SESSION))
          window.__video2agentLiveState = () => ({
            activeSession: ACTIVE_SESSION,
            any: LIVE_ANY,
            sessions: [...LIVE_BY_SESSION.entries()],
          })
        }
        slots.inject('conversation.input.dock', () => slots.register(
          { name: 'conversation.input.dock', id: 'video2agent-status', order: 3 },
          LiveStrip,
        ))
        slots.inject('conversation.input.dock', () => slots.register(
          { name: 'conversation.input.dock', id: 'video2agent-activity', order: 3.2 },
          ActivityStrip,
        ))
        slots.inject('conversation.input.dock', () => slots.register(
          { name: 'conversation.input.dock', id: 'video2agent-queue', order: 3.5 },
          QueueStrip,
        ))
        slots.inject('conversation.input.dock', () => slots.register(
          { name: 'conversation.input.dock', id: 'video2agent-search', order: 4 },
          SearchStatus,
        ))
        slots.inject('conversation.input.dock', () => slots.register(
          { name: 'conversation.input.dock', id: 'video2agent-link-preview', order: 5 },
          LinkPreview,
        ))
        slots.inject('settings.section', () => slots.register(
          { name: 'settings.section', id: 'video2agent', order: 30, label: 'Video2Agent' },
          SettingsSection,
        ))
        slots.inject('plugins.bundle.config', () => slots.register(
          { name: 'plugins.bundle.config', key: 'dsh-video2agent' },
          SettingsSection,
        ))
      },
    }
  },
})
