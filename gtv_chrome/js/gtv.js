/* ============================================================
   Genius TV — Chrome Ambient Display
   Main JS: art rotation, clock, weather, voice, exit.
   ============================================================ */

window.gtv = (() => {
    'use strict';

    // ---- Art collection ----
    const ART = [
        'rembrandt_selfportrait', 'rembrandt_storm', 'vermeer_milkmaid',
        'vermeer_viewdelft', 'monet_sunrise', 'monet_garden', 'monet_parliament',
        'vangogh_cafe', 'vangogh_sunflowers', 'vangogh_wheatfield',
        'davinci_lady', 'davinci_supper', 'botticelli_spring',
        'raphael_athens', 'raphael_sistine', 'caravaggio_calling', 'titian_venus',
        'elgreco_view', 'velazquez_lasmeninas', 'velazquez_venus', 'goya_thirdmay',
        'goya_saturn', 'durer_hare', 'durer_hands', 'bruegel_hunters', 'bruegel_tower',
        'hals_laughing', 'vermeer_astronomer', 'vermeer_guitar', 'monet_poppies',
        'monet_bridge', 'vangogh_almond', 'vangogh_selfportrait',
        'sorolla_children', 'sorolla_walk', 'hassam_allies', 'sargent_carnation',
        'sargent_madame', 'turner_rain', 'turner_fighting', 'hokusai_wave',
        'hopper_nighthawks', 'whistler_arrangement'
    ];

    const ART_TITLES = {
        rembrandt_selfportrait: 'Rembrandt — Self-Portrait',
        rembrandt_storm: 'Rembrandt — The Storm on the Sea of Galilee',
        vermeer_milkmaid: 'Vermeer — The Milkmaid',
        vermeer_viewdelft: 'Vermeer — View of Delft',
        monet_sunrise: 'Monet — Impression, Sunrise',
        monet_garden: 'Monet — Garden at Sainte-Adresse',
        monet_parliament: 'Monet — Houses of Parliament',
        vangogh_cafe: 'Van Gogh — Café Terrace at Night',
        vangogh_sunflowers: 'Van Gogh — Sunflowers',
        vangogh_wheatfield: 'Van Gogh — Wheatfield with Crows',
        davinci_lady: 'Da Vinci — Lady with an Ermine',
        davinci_supper: 'Da Vinci — The Last Supper',
        botticelli_spring: 'Botticelli — Primavera',
        raphael_athens: 'Raphael — The School of Athens',
        raphael_sistine: 'Raphael — Sistine Madonna',
        caravaggio_calling: 'Caravaggio — The Calling of Saint Matthew',
        titian_venus: 'Titian — Venus of Urbino',
        elgreco_view: 'El Greco — View of Toledo',
        velazquez_lasmeninas: 'Velázquez — Las Meninas',
        velazquez_venus: 'Velázquez — Rokeby Venus',
        goya_thirdmay: 'Goya — The Third of May 1808',
        goya_saturn: 'Goya — Saturn Devouring His Son',
        durer_hare: 'Dürer — Young Hare',
        durer_hands: 'Dürer — Praying Hands',
        bruegel_hunters: 'Bruegel — Hunters in the Snow',
        bruegel_tower: 'Bruegel — The Tower of Babel',
        hals_laughing: 'Hals — Laughing Cavalier',
        vermeer_astronomer: 'Vermeer — The Astronomer',
        vermeer_guitar: 'Vermeer — The Guitar Player',
        monet_poppies: 'Monet — Poppies',
        monet_bridge: 'Monet — The Water-Lily Pond',
        vangogh_almond: 'Van Gogh — Almond Blossom',
        vangogh_selfportrait: 'Van Gogh — Self-Portrait',
        sorolla_children: 'Sorolla — Children on the Beach',
        sorolla_walk: 'Sorolla — Walk on the Beach',
        hassam_allies: 'Hassam — Allies Day, May 1917',
        sargent_carnation: 'Sargent — Carnation, Lily, Lily, Rose',
        sargent_madame: 'Sargent — Madame X',
        turner_rain: 'Turner — Rain, Steam and Speed',
        turner_fighting: 'Turner — The Fighting Temeraire',
        hokusai_wave: 'Hokusai — The Great Wave off Kanagawa',
        hopper_nighthawks: 'Hopper — Nighthawks',
        whistler_arrangement: 'Whistler — Arrangement in Grey and Black'
    };

    let artIndex = 0;
    let artOrder = [];
    let artPos = -1;
    let passCount = 0;
    let barAtTop = false;
    let barLayout = 0;
    let cursorVisible = false;
    let cursorTimer = null;

    function shuffleArtOrder() {
        artOrder = ART.map((_, i) => i);
        for (let i = artOrder.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [artOrder[i], artOrder[j]] = [artOrder[j], artOrder[i]];
        }
        if (artOrder.length > 1 && artOrder[0] === artIndex) {
            [artOrder[0], artOrder[1]] = [artOrder[1], artOrder[0]];
        }
        artPos = -1;
    }

    function nextArt() {
        if (artOrder.length !== ART.length) shuffleArtOrder();
        artPos++;
        if (artPos >= artOrder.length) {
            passCount++;
            if (passCount >= 2 + Math.floor(Math.random() * 2)) {
                passCount = 0;
                shuffleArtOrder();
            }
            artPos = 0;
        }
        artIndex = artOrder[artPos];
        return ART[artIndex];
    }

    function updateClock() {
        const now = new Date();
        const h = now.getHours();
        const m = now.getMinutes();
        const ampm = h >= 12 ? 'PM' : 'AM';
        const h12 = h % 12 || 12;
        document.getElementById('clock').textContent = `${h12}:${m.toString().padStart(2, '0')} ${ampm}`;
        
        const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        const months = ['January', 'February', 'March', 'April', 'May', 'June',
                       'July', 'August', 'September', 'October', 'November', 'December'];
        document.getElementById('date').textContent = `${days[now.getDay()]}, ${months[now.getMonth()]} ${now.getDate()}`;
    }

    async function updateWeather() {
        try {
            const resp = await fetch('/api/weather');
            if (resp.ok) {
                const data = await resp.json();
                document.getElementById('weather').textContent = `${data.summary}${data.detail ? ' · ' + data.detail : ''}`;
            } else {
                document.getElementById('weather').textContent = '—';
            }
        } catch (e) {
            document.getElementById('weather').textContent = '—';
        }
    }

    function migrateBar() {
        barAtTop = !barAtTop;
        const bar = document.getElementById('info-bar');
        bar.className = barAtTop ? 'top' : 'bottom';
    }

    function permuteBar() {
        barLayout = (barLayout + 1) % 3;
        const start = document.getElementById('brand-start');
        const end = document.getElementById('brand-end');
        start.style.display = barLayout === 0 ? '' : 'none';
        end.style.display = barLayout !== 0 ? '' : 'none';
    }

    function rotateArt() {
        const next = nextArt();
        const title = ART_TITLES[next] || next.replace(/_/g, ' ');
        document.getElementById('art-title').textContent = title;
        showBar();  // brief bar visibility on each painting change

        const artNext = document.getElementById('art-next');
        const artCurrent = document.getElementById('art-current');

        artNext.src = `art/${next}.jpg`;
        artNext.onload = () => {
            artNext.style.opacity = '1';
            artCurrent.style.opacity = '0';
            setTimeout(() => {
                artCurrent.src = artNext.src;
                artCurrent.style.opacity = '1';
                artNext.style.opacity = '0';
            }, 2000);
        };
    }

    function showBar() {
        const bar = document.getElementById('info-bar');
        bar.style.opacity = '1';
        clearTimeout(bar._fadeTimer);
        bar._fadeTimer = setTimeout(() => { bar.style.opacity = '0'; }, 8000);
    }

    function setVoiceState(state) {
        const el = document.getElementById('voice-state');
        el.className = state;
        const labels = { idle: '', listening: 'Listening…', thinking: 'Thinking…', reply: 'Speaking…', playing: 'Playing…' };
        document.getElementById('caption').textContent = labels[state] || '';
    }

    function setTranscript(text) {
        document.getElementById('transcript').textContent = text;
    }

    function showVoiceOverlay() {
        document.getElementById('voice-overlay').classList.add('active');
    }

    function hideVoiceOverlay() {
        document.getElementById('voice-overlay').classList.remove('active');
    }

    function showCursor() {
        cursorVisible = true;
        document.body.style.cursor = 'default';
        const exitBtn = document.getElementById('exit-btn');
        if (exitBtn) exitBtn.style.opacity = '0.7';
        clearTimeout(cursorTimer);
        cursorTimer = setTimeout(hideCursor, 4000);
    }

    function hideCursor() {
        cursorVisible = false;
        document.body.style.cursor = 'none';
        const exitBtn = document.getElementById('exit-btn');
        if (exitBtn) exitBtn.style.opacity = '0';
    }

    function quit() {
        // Send quit message to parent or close
        if (window.chrome && window.chrome.webview) {
            window.chrome.webview.postMessage('quit');
        } else {
            window.close();
        }
    }

    function init() {
        // Set initial art
        const first = ART[0];
        document.getElementById('art-current').src = `art/${first}.jpg`;
        document.getElementById('art-title').textContent = ART_TITLES[first] || first;

        // Initialize GENIUS TV brand visibility (start shown, end hidden)
        document.getElementById('brand-start').style.display = '';
        document.getElementById('brand-end').style.display = 'none';

        // Timers
        updateClock();
        setInterval(updateClock, 1000);

        updateWeather();
        setInterval(updateWeather, 600000);

        rotateArt();
        setInterval(rotateArt, 30000);

        migrateBar();
        setInterval(migrateBar, 300000);

        setInterval(permuteBar, 240000);

        // Mouse cursor management
        document.addEventListener('mousemove', showCursor);
        document.addEventListener('mousedown', showCursor);
        hideCursor();

        // Keyboard shortcuts for exit
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' || e.key === 'q' || e.key === 'Q') {
                quit();
            }
        });

        // Prevent right-click menu
        document.addEventListener('contextmenu', (e) => e.preventDefault());

        // Simulate wake word (for testing)
        console.log('Genius TV Chrome initialized');
    }

    return { init, quit, setVoiceState, setTranscript, showVoiceOverlay, hideVoiceOverlay };
})();

window.addEventListener('DOMContentLoaded', window.gtv.init);
