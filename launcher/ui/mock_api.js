// Fake backend for previewing the UI in a normal browser (open preview.html).
// In the real launcher, window.pywebview.api is provided by Python (see webapp_gears5_example.py).
(function () {
  const state = {
    title: 'Example Game — Enemy models',
    installed: false,
    can_uninstall: true,
    categories: [['Soldiers', ['grunt', 'sniper']], ['Heavies', ['brute']]],
    acts: [['act1', 'Act 1'], ['act2', 'Act 2']],
    no_campaign: 'Multiplayer only',
    enemies: {
      grunt: { name: 'Grunt', acts: ['act1', 'act2'] },
      sniper: { name: 'Sniper', acts: ['act2'] },
      brute: { name: 'Brute', acts: [] },
    },
    tabs: ['Women', 'Men', 'Robots'],
    models: [
      { key: 'anna', name: 'Anna (Default)', tab: 'Women', group: 'Anna' },
      { key: 'anna_armor', name: 'Anna (Armor)', tab: 'Women', group: 'Anna' },
      { key: 'bea', name: 'Bea', tab: 'Women', group: 'Bea' },
      { key: 'carl', name: 'Carl', tab: 'Men', group: 'Carl' },
      { key: 'bot', name: 'Bot Mk1', tab: 'Robots', group: 'Bots' },
    ],
    assign: { grunt: ['anna'], sniper: [], brute: [] },
    options: [{ key: 'example', label: 'Example option', value: true }],
    message: 'Preview with fake data.',
  };
  state.modelNames = Object.fromEntries(state.models.map((m) => [m.key, m.name]));

  function fakeWork(done) {
    ui.busy(true);
    let f = 0;
    const t = setInterval(() => {
      f += 0.1;
      ui.progress(f);
      if (f >= 1) { clearInterval(t); ui.busy(false); done(); ui.refresh(); }
    }, 120);
  }

  window.pywebview = {
    api: {
      get_state: async () => JSON.parse(JSON.stringify(state)),
      save_assign: async (a) => { state.assign = a; },
      set_option: async (key, value) => { state.options.find((o) => o.key === key).value = value; },
      apply: async (a, launch) => {
        state.assign = a;
        fakeWork(() => {
          state.installed = Object.values(a).some((l) => l.length);
          ui.status(launch ? 'Launching the game...' : 'Ready.');
        });
      },
      restore: async () => fakeWork(() => {
        state.installed = false;
        for (const e in state.assign) state.assign[e] = [];
        ui.status('Original game restored.');
      }),
      uninstall: async () => ui.status('(preview) uninstall'),
    },
  };
})();
