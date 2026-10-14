// CatWandConnect joystick card for Home Assistant dashboards.
//
// Mirrors the joystick of the robot's Device interface: hold and drag the knob,
// the wand follows; release it and the wand stops. While held, the card sends
// `catwandconnect/move` to Home Assistant every 100 ms, which forwards it to the
// robot. The robot stops by itself if no move arrives for 500 ms, so a closed
// tab or a lost network never leaves the wand moving.
//
// Served by the integration and loaded on every dashboard: no resource to add.
//
//   type: custom:catwandconnect-joystick-card
//   device_id: <the robot's device id>   # or entity: sensor.catwandconnect_activity
//   title: Wand                           # optional

const DOMAIN = 'catwandconnect';
const SEND_INTERVAL_MS = 100;

const STRINGS = {
  en: {
    name: 'CatWandConnect joystick',
    description: 'Move the wand like the robot\'s own joystick: hold and drag, release to stop.',
    hint: 'Hold and drag to move the wand',
    unavailable: 'Robot offline',
    no_device: 'Choose a CatWandConnect robot in the card settings.',
    activity: 'Activity',
    horizontal: 'Horizontal',
    vertical: 'Vertical',
    device_id: 'Robot',
    title: 'Title (optional)',
  },
  fr: {
    name: 'Joystick CatWandConnect',
    description: 'Déplace la baguette comme avec le joystick du robot : maintiens et fais glisser, relâche pour arrêter.',
    hint: 'Maintiens et fais glisser pour déplacer la baguette',
    unavailable: 'Robot hors ligne',
    no_device: 'Choisis un robot CatWandConnect dans les réglages de la carte.',
    activity: 'Activité',
    horizontal: 'Horizontal',
    vertical: 'Vertical',
    device_id: 'Robot',
    title: 'Titre (facultatif)',
  },
};

function strings(hass) {
  const lang = (hass?.locale?.language || hass?.language || navigator.language || 'en').slice(0, 2);
  return STRINGS[lang] || STRINGS.en;
}

function robotEntities(hass) {
  return Object.values(hass?.entities || {}).filter(e => e.platform === DOMAIN);
}

function firstRobot(hass) {
  return robotEntities(hass).find(e => e.device_id)?.device_id;
}

const STYLE = `
  ha-card { padding: 16px; display: flex; flex-direction: column; align-items: center; gap: 12px; }
  .title { align-self: stretch; font-size: var(--ha-card-header-font-size, 1.5rem); color: var(--ha-card-header-color, var(--primary-text-color)); }
  .pad {
    position: relative;
    width: min(100%, 18rem);
    aspect-ratio: 1;
    border-radius: 50%;
    background: var(--secondary-background-color);
    border: 2px solid var(--divider-color);
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    cursor: grab;
    box-sizing: border-box;
  }
  .pad.active { cursor: grabbing; }
  .pad.disabled { opacity: .4; cursor: not-allowed; }
  .knob {
    position: absolute;
    inset: 30%;
    border-radius: 50%;
    background: var(--primary-color);
    box-shadow: 0 4px 12px rgb(0 0 0 / 25%);
    pointer-events: none;
  }
  .pad.active .knob { transition: none; }
  .pad:not(.active) .knob { transition: transform .15s ease-out; }
  .hint { color: var(--secondary-text-color); font-size: .9rem; text-align: center; margin: 0; }
  .status { display: flex; flex-wrap: wrap; justify-content: center; gap: 4px 16px; color: var(--primary-text-color); font-size: .9rem; margin: 0; }
  .status span span { color: var(--secondary-text-color); }
  .warning { color: var(--error-color); }
`;

class CatWandConnectJoystickCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._deflection = null;
    this._timer = null;
    this._onVisibility = () => { if (document.hidden) this._release(); };
  }

  static getStubConfig(hass) {
    const deviceId = firstRobot(hass);
    return deviceId ? { device_id: deviceId } : {};
  }

  static getConfigElement() {
    return document.createElement('catwandconnect-joystick-card-editor');
  }

  setConfig(config) {
    if (!config) throw new Error('Invalid configuration');
    this._config = { ...config };
    this._built = false;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  get hass() { return this._hass; }

  getCardSize() { return 6; }

  getGridOptions() { return { columns: 6, min_columns: 4, rows: 'auto' }; }

  connectedCallback() {
    document.addEventListener('visibilitychange', this._onVisibility);
  }

  disconnectedCallback() {
    document.removeEventListener('visibilitychange', this._onVisibility);
    this._release();
  }

  get _deviceId() {
    const config = this._config || {};
    if (config.device_id) return config.device_id;
    if (config.entity) return this._hass?.entities?.[config.entity]?.device_id;
    return undefined;
  }

  _entity(key) {
    const deviceId = this._deviceId;
    return robotEntities(this._hass).find(e => e.device_id === deviceId && (
      e.translation_key === key || e.entity_id.endsWith(`_${key}`)));
  }

  _state(key) {
    const entry = this._entity(key);
    return entry ? this._hass.states[entry.entity_id] : undefined;
  }

  _format(stateObj) {
    if (!stateObj) return '–';
    if (typeof this._hass.formatEntityState === 'function') return this._hass.formatEntityState(stateObj);
    const unit = stateObj.attributes?.unit_of_measurement;
    return unit ? `${stateObj.state} ${unit}` : stateObj.state;
  }

  get _available() {
    const activity = this._state('activity');
    return !!activity && activity.state !== 'unavailable' && activity.state !== 'unknown';
  }

  _build() {
    const t = strings(this._hass);
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="title" hidden></div>
        <div class="pad" role="application" aria-label="${t.hint}"><div class="knob"></div></div>
        <p class="hint"></p>
        <p class="status">
          <span><span class="l-activity"></span> <b class="activity"></b></span>
          <span><span class="l-h"></span> <b class="h"></b></span>
          <span><span class="l-v"></span> <b class="v"></b></span>
        </p>
      </ha-card>`;
    this._pad = this.shadowRoot.querySelector('.pad');
    this._knob = this.shadowRoot.querySelector('.knob');
    this._pad.addEventListener('pointerdown', e => this._press(e));
    this._pad.addEventListener('pointermove', e => { if (this._deflection) this._track(e); });
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      this._pad.addEventListener(type, () => this._release());
    }
    this._built = true;
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._built) this._build();
    const t = strings(this._hass);
    const root = this.shadowRoot;
    const title = root.querySelector('.title');
    title.hidden = !this._config.title;
    title.textContent = this._config.title || '';

    const hint = root.querySelector('.hint');
    const available = !!this._deviceId && this._available;
    this._pad.classList.toggle('disabled', !available);
    if (!this._deviceId) {
      hint.textContent = t.no_device;
      hint.classList.add('warning');
    } else if (!available) {
      hint.textContent = t.unavailable;
      hint.classList.add('warning');
    } else {
      hint.textContent = t.hint;
      hint.classList.remove('warning');
    }
    if (!available) this._release();

    root.querySelector('.status').hidden = !this._deviceId;
    root.querySelector('.l-activity').textContent = `${t.activity}:`;
    root.querySelector('.l-h').textContent = `${t.horizontal}:`;
    root.querySelector('.l-v').textContent = `${t.vertical}:`;
    root.querySelector('.activity').textContent = this._format(this._state('activity'));
    root.querySelector('.h').textContent = this._format(this._state('horizontal_position'));
    root.querySelector('.v').textContent = this._format(this._state('vertical_position'));
  }

  _press(event) {
    if (!this._deviceId || !this._available) return;
    event.preventDefault();
    this._pad.setPointerCapture(event.pointerId);
    this._pad.classList.add('active');
    this._track(event);
    this._sendMove();
    clearInterval(this._timer);
    this._timer = setInterval(() => this._sendMove(), SEND_INTERVAL_MS);
  }

  _track(event) {
    const box = this._pad.getBoundingClientRect();
    const radius = box.width / 2;
    let x = (event.clientX - box.left - radius) / radius;
    let y = -(event.clientY - box.top - radius) / radius;
    const length = Math.hypot(x, y);
    if (length > 1) { x /= length; y /= length; }
    this._deflection = { x, y };
    const travel = radius * 0.6;  // the knob's edge stays inside the pad
    this._knob.style.transform = `translate(${x * travel}px, ${-y * travel}px)`;
  }

  _send(message) {
    const deviceId = this._deviceId;
    if (!deviceId || !this._hass?.connection) return;
    this._hass.connection
      .sendMessagePromise({ type: `${DOMAIN}/${message.type}`, device_id: deviceId, ...message.data })
      .catch(() => { /* offline robot: the pad greys out with the entities */ });
  }

  _sendMove() {
    if (!this._deflection) return;
    const round = value => Math.round(value * 100) / 100;
    this._send({ type: 'move', data: { h: round(this._deflection.x), v: round(this._deflection.y) } });
  }

  _release() {
    clearInterval(this._timer);
    this._timer = null;
    if (!this._deflection) return;
    this._deflection = null;
    if (this._pad) {
      this._pad.classList.remove('active');
      this._knob.style.transform = '';
    }
    this._send({ type: 'stop' });
  }
}

class CatWandConnectJoystickCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    const t = strings(this._hass);
    if (!this._form) {
      this._form = document.createElement('ha-form');
      this._form.computeLabel = schema => t[schema.name] || schema.name;
      this._form.addEventListener('value-changed', event => {
        const config = { ...event.detail.value };
        if (!config.title) delete config.title;
        this._config = config;
        this.dispatchEvent(new CustomEvent('config-changed', {
          detail: { config }, bubbles: true, composed: true,
        }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: 'device_id', required: true, selector: { device: { integration: DOMAIN } } },
      { name: 'title', selector: { text: {} } },
    ];
  }
}

if (!customElements.get('catwandconnect-joystick-card')) {
  customElements.define('catwandconnect-joystick-card', CatWandConnectJoystickCard);
  customElements.define('catwandconnect-joystick-card-editor', CatWandConnectJoystickCardEditor);
  const t = strings({ language: document.documentElement.lang });
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'catwandconnect-joystick-card',
    name: t.name,
    description: t.description,
    preview: false,
    documentationURL: 'https://github.com/vistorx/ha-catwandconnect#joystick-card',
  });
}
