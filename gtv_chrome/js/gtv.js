/* ============================================================
   Genius TV — Chrome Ambient Display
   Main JS: art rotation, clock, weather, voice, exit.
   ============================================================ */

window.gtv = (() => {
    'use strict';

    // ---- Art collection ----
    const ART = [
        'botticelli_spring', 'bruegel_hunters', 'bruegel_tower',
        'caillebotte_boating', 'caillebotte_floor', 'caillebotte_man_balcony',
        'caillebotte_orange_trees', 'caillebotte_paris', 'caillebotte_rainy',
        'caravaggio_calling', 'cassatt_boating', 'cassatt_child_bath',
        'cassatt_lilacs_window', 'cassatt_mother_child', 'cassatt_opera',
        'cassatt_tea', 'cassatt_tea_table', 'cezanne_apples',
        'cezanne_bathers', 'cezanne_cardplayers', 'cezanne_house_provence',
        'cezanne_mont_sainte_large', 'cezanne_saintevictoire', 'cezanne_still_life_curtain',
        'constable_haywain', 'davinci_lady', 'davinci_supper',
        'degas_absinthe', 'degas_ballet', 'degas_cafe_concert',
        'degas_dance_class', 'degas_dancers_bar', 'degas_dancers_blue',
        'degas_little_dancer', 'degas_milliners', 'degas_racehorses',
        'degas_rehearsal', 'delacroix_liberty', 'durer_hands',
        'durer_hare', 'elgreco_view', 'friedrich_wanderer',
        'gauguin_tahiti_women', 'gauguin_tahitian_landscape', 'gauguin_vision',
        'gauguin_where_do_we_come', 'gauguin_yellow_christ', 'goya_saturn',
        'goya_thirdmay', 'hals_laughing', 'hassam_flags',
        'hassam_poppies_isle', 'hassam_rainy_boston', 'hassam_rue_daunou',
        'hokusai_great_wave', 'hopper_nighthawks', 'ingres_bath',
        'klimt_adele', 'klimt_kiss', 'manet_balcony',
        'manet_boating', 'manet_dejeuner', 'manet_folies_bergere',
        'manet_garden_ruel', 'manet_olympia', 'manet_railroad',
        'matisse_dance', 'monet_argenteuil', 'monet_argenteuil_boats',
        'monet_boats_argenteuil', 'monet_bridge', 'monet_garden',
        'monet_giverny_morning', 'monet_haystacks_morning', 'monet_haystacks_sunset',
        'monet_japanese_bridge', 'monet_london_parliament', 'monet_parliament',
        'monet_poppies', 'monet_poppy_field', 'monet_rouen_cathedral',
        'monet_sunrise', 'monet_terrace_sainte', 'monet_tulips_holland',
        'monet_veheuil', 'monet_waterlilies_1906', 'monet_waterlilies_1907',
        'monet_waterlilies_clouds', 'monet_waterlily_pond', 'monet_woman_parasol',
        'morisot_cherry_tree', 'morisot_cradle', 'morisot_harbour',
        'morisot_reading', 'morisot_summer_day', 'morisot_woman_dressing',
        'munch_scream', 'picasso_avignon', 'pissarro_boulevard',
        'pissarro_boulevard_morning', 'pissarro_eragny', 'pissarro_haying_eragny',
        'pissarro_orchard', 'pissarro_orchard_spring', 'pissarro_red_roofs',
        'raphael_athens', 'raphael_sistine', 'rembrandt_selfportrait',
        'rembrandt_storm', 'renoir_boating', 'renoir_dance_bougival',
        'renoir_dance_city', 'renoir_dance_country', 'renoir_garden_montmartre',
        'renoir_girls_piano', 'renoir_moulin', 'renoir_swing',
        'renoir_two_sisters', 'renoir_umbrellas', 'sargent_carnation',
        'sargent_daughters_boit', 'sargent_gondola', 'sargent_madame_x',
        'sargent_watercolours', 'seurat_bathers', 'seurat_circus',
        'seurat_grande_jatte', 'seurat_models', 'seurat_seine_grande_jatte',
        'sisley_autumn_banks', 'sisley_bridge_villeneuve', 'sisley_canal_saint_mammes',
        'sisley_flood', 'sisley_moret_sun', 'sisley_snow_louveciennes',
        'sorolla_beach', 'sorolla_children_sea', 'sorolla_fishing',
        'sorolla_strolling_beach', 'sorolla_walk', 'titian_venus',
        'toulouse_moulin_rouge', 'turner_fighting_temeraire', 'turner_rain_steam',
        'vangogh_almond', 'vangogh_bedroom', 'vangogh_cafe',
        'vangogh_church', 'vangogh_cypresses', 'vangogh_irises',
        'vangogh_night_cafe', 'vangogh_olive_trees', 'vangogh_roses',
        'vangogh_selfportrait', 'vangogh_starry_night', 'vangogh_starry_rhone',
        'vangogh_sunflowers', 'vangogh_wheatfield', 'velazquez_lasmeninas',
        'velazquez_venus', 'vermeer_astronomer', 'vermeer_guitar',
        'vermeer_milkmaid', 'vermeer_viewdelft', 'whistler_mother',
    ];

    const ART_TITLES = {
        botticelli_spring: 'Botticelli — Primavera',
        bruegel_hunters: 'Bruegel — Hunters in the Snow',
        bruegel_tower: 'Bruegel — The Tower of Babel',
        caillebotte_boating: 'Caillebotte — Boating on the Yerres',
        caillebotte_floor: 'Caillebotte — The Floor Scrapers',
        caillebotte_man_balcony: 'Caillebotte — Man on a Balcony',
        caillebotte_orange_trees: 'Caillebotte — Orange Trees',
        caillebotte_paris: 'Caillebotte — Paris Street, Rainy Day',
        caillebotte_rainy: 'Caillebotte — Paris Street, Rainy Day',
        caravaggio_calling: 'Caravaggio — The Calling of Saint Matthew',
        cassatt_boating: 'Cassatt — The Boating Party',
        cassatt_child_bath: 'Cassatt — The Child\'s Bath',
        cassatt_lilacs_window: 'Cassatt — Lilacs in a Window',
        cassatt_mother_child: 'Cassatt — Mother and Child',
        cassatt_opera: 'Cassatt — In the Loge',
        cassatt_tea: 'Cassatt — Tea',
        cassatt_tea_table: 'Cassatt — Lady at the Tea Table',
        cezanne_apples: 'Cézanne — Still Life with Apples',
        cezanne_bathers: 'Cézanne — The Bathers',
        cezanne_cardplayers: 'Cézanne — The Card Players',
        cezanne_house_provence: 'Cézanne — House in Provence',
        cezanne_mont_sainte_large: 'Cézanne — Mont Sainte-Victoire (Large)',
        cezanne_saintevictoire: 'Cézanne — Mont Sainte-Victoire',
        cezanne_still_life_curtain: 'Cézanne — Still Life with Curtain',
        constable_haywain: 'Constable — The Hay Wain',
        davinci_lady: 'Da Vinci — Lady with an Ermine',
        davinci_supper: 'Da Vinci — The Last Supper',
        degas_absinthe: 'Degas — L\'Absinthe',
        degas_ballet: 'Degas — Ballet',
        degas_cafe_concert: 'Degas — At the Café Concert',
        degas_dance_class: 'Degas — The Dance Class',
        degas_dancers_bar: 'Degas — Dancers at the Bar',
        degas_dancers_blue: 'Degas — Blue Dancers',
        degas_little_dancer: 'Degas — Little Dancer of Fourteen',
        degas_milliners: 'Degas — The Milliners',
        degas_racehorses: 'Degas — Racehorses at Longchamp',
        degas_rehearsal: 'Degas — The Rehearsal',
        delacroix_liberty: 'Delacroix — Liberty Leading the People',
        durer_hands: 'Dürer — Praying Hands',
        durer_hare: 'Dürer — Young Hare',
        elgreco_view: 'El Greco — View of Toledo',
        friedrich_wanderer: 'Friedrich — Wanderer above the Sea of Fog',
        gauguin_tahiti_women: 'Gauguin — Two Tahitian Women',
        gauguin_tahitian_landscape: 'Gauguin — Tahitian Landscape',
        gauguin_vision: 'Gauguin — Vision after the Sermon',
        gauguin_where_do_we_come: 'Gauguin — Where Do We Come From?',
        gauguin_yellow_christ: 'Gauguin — The Yellow Christ',
        goya_saturn: 'Goya — Saturn Devouring His Son',
        goya_thirdmay: 'Goya — The Third of May 1808',
        hals_laughing: 'Hals — Laughing Cavalier',
        hassam_flags: 'Hassam — Allies Day, May 1917',
        hassam_poppies_isle: 'Hassam — Poppies on the Isle of Shoals',
        hassam_rainy_boston: 'Hassam — Rainy Day, Boston',
        hassam_rue_daunou: 'Hassam — July Fourteenth, Rue Daunou',
        hokusai_great_wave: 'Hokusai — The Great Wave off Kanagawa',
        hopper_nighthawks: 'Hopper — Nighthawks',
        ingres_bath: 'Ingres — The Valpinçon Bather',
        klimt_adele: 'Klimt — Portrait of Adele Bloch-Bauer',
        klimt_kiss: 'Klimt — The Kiss',
        manet_balcony: 'Manet — The Balcony',
        manet_boating: 'Manet — Boating',
        manet_dejeuner: 'Manet — Le Déjeuner sur l\'herbe',
        manet_folies_bergere: 'Manet — A Bar at the Folies-Bergère',
        manet_garden_ruel: 'Manet — A Lane in the Garden at Rueil',
        manet_olympia: 'Manet — Olympia',
        manet_railroad: 'Manet — The Railway',
        matisse_dance: 'Matisse — Dance',
        monet_argenteuil: 'Monet — Argenteuil',
        monet_argenteuil_boats: 'Monet — The Bridge at Argenteuil',
        monet_boats_argenteuil: 'Monet — Boats at Argenteuil',
        monet_bridge: 'Monet — The Water-Lily Pond',
        monet_garden: 'Monet — Garden at Sainte-Adresse',
        monet_giverny_morning: 'Monet — Morning at Giverny',
        monet_haystacks_morning: 'Monet — Haystacks (Morning)',
        monet_haystacks_sunset: 'Monet — Stacks of Wheat (Sunset)',
        monet_japanese_bridge: 'Monet — The Japanese Bridge',
        monet_london_parliament: 'Monet — Houses of Parliament, London',
        monet_parliament: 'Monet — Houses of Parliament',
        monet_poppies: 'Monet — Poppies',
        monet_poppy_field: 'Monet — Poppy Field near Argenteuil',
        monet_rouen_cathedral: 'Monet — Rouen Cathedral, Full Sunlight',
        monet_sunrise: 'Monet — Impression, Sunrise',
        monet_terrace_sainte: 'Monet — Garden at Sainte-Adresse',
        monet_tulips_holland: 'Monet — Tulips in Holland',
        monet_veheuil: 'Monet — Vétheuil in Summer',
        monet_waterlilies_1906: 'Monet — Water Lilies (1906)',
        monet_waterlilies_1907: 'Monet — Water Lilies (1907)',
        monet_waterlilies_clouds: 'Monet — Water Lilies and Clouds',
        monet_waterlily_pond: 'Monet — The Water-Lily Pond',
        monet_woman_parasol: 'Monet — Woman with a Parasol',
        morisot_cherry_tree: 'Morisot — The Cherry Tree',
        morisot_cradle: 'Morisot — The Cradle',
        morisot_harbour: 'Morisot — The Harbor at Lorient',
        morisot_reading: 'Morisot — Reading',
        morisot_summer_day: 'Morisot — Summer\'s Day',
        morisot_woman_dressing: 'Morisot — Woman at Her Toilette',
        munch_scream: 'Munch — The Scream',
        picasso_avignon: 'Picasso — Les Demoiselles d\'Avignon',
        pissarro_boulevard: 'Pissarro — Boulevard Montmartre at Night',
        pissarro_boulevard_morning: 'Pissarro — Boulevard Montmartre, Morning',
        pissarro_eragny: 'Pissarro — The Garden at Éragny',
        pissarro_haying_eragny: 'Pissarro — Haying at Éragny',
        pissarro_orchard: 'Pissarro — The Garden of Les Mathurins',
        pissarro_orchard_spring: 'Pissarro — Orchard in Spring',
        pissarro_red_roofs: 'Pissarro — Red Roofs',
        raphael_athens: 'Raphael — The School of Athens',
        raphael_sistine: 'Raphael — Sistine Madonna',
        rembrandt_selfportrait: 'Rembrandt — Self-Portrait',
        rembrandt_storm: 'Rembrandt — The Storm on the Sea of Galilee',
        renoir_boating: 'Renoir — Luncheon of the Boating Party',
        renoir_dance_bougival: 'Renoir — Dance at Bougival',
        renoir_dance_city: 'Renoir — Dance in the City',
        renoir_dance_country: 'Renoir — Dance in the Country',
        renoir_garden_montmartre: 'Renoir — The Garden in Montmartre',
        renoir_girls_piano: 'Renoir — Young Girls at the Piano',
        renoir_moulin: 'Renoir — Bal du moulin de la Galette',
        renoir_swing: 'Renoir — The Swing',
        renoir_two_sisters: 'Renoir — Two Sisters (On the Terrace)',
        renoir_umbrellas: 'Renoir — The Umbrellas',
        sargent_carnation: 'Sargent — Carnation, Lily, Lily, Rose',
        sargent_daughters_boit: 'Sargent — The Daughters of Edward Boit',
        sargent_gondola: 'Sargent — A Gondola in Venice',
        sargent_madame_x: 'Sargent — Madame X',
        sargent_watercolours: 'Sargent — Watercolours',
        seurat_bathers: 'Seurat — Bathers at Asnières',
        seurat_circus: 'Seurat — The Circus',
        seurat_grande_jatte: 'Seurat — A Sunday on La Grande Jatte',
        seurat_models: 'Seurat — Models (Poseuses)',
        seurat_seine_grande_jatte: 'Seurat — The Seine at La Grande Jatte',
        sisley_autumn_banks: 'Sisley — Autumn Banks of the Seine',
        sisley_bridge_villeneuve: 'Sisley — The Bridge at Villeneuve',
        sisley_canal_saint_mammes: 'Sisley — The Canal of Saint-Mammès',
        sisley_flood: 'Sisley — Flood at Port-Marly',
        sisley_moret_sun: 'Sisley — Moret-sur-Loing in the Sun',
        sisley_snow_louveciennes: 'Sisley — Snow at Louveciennes',
        sorolla_beach: 'Sorolla — Children on the Beach',
        sorolla_children_sea: 'Sorolla — Children on the Sea',
        sorolla_fishing: 'Sorolla — The Return from Fishing',
        sorolla_strolling_beach: 'Sorolla — Strolling along the Beach',
        sorolla_walk: 'Sorolla — Walk on the Beach',
        titian_venus: 'Titian — Venus of Urbino',
        toulouse_moulin_rouge: 'Toulouse-Lautrec — At the Moulin Rouge',
        turner_fighting_temeraire: 'Turner — The Fighting Temeraire',
        turner_rain_steam: 'Turner — Rain, Steam and Speed',
        vangogh_almond: 'Van Gogh — Almond Blossom',
        vangogh_bedroom: 'Van Gogh — Bedroom in Arles',
        vangogh_cafe: 'Van Gogh — Café Terrace at Night',
        vangogh_church: 'Van Gogh — The Church at Auvers',
        vangogh_cypresses: 'Van Gogh — Cypresses',
        vangogh_irises: 'Van Gogh — Irises',
        vangogh_night_cafe: 'Van Gogh — The Night Café',
        vangogh_olive_trees: 'Van Gogh — Olive Trees',
        vangogh_roses: 'Van Gogh — Roses',
        vangogh_selfportrait: 'Van Gogh — Self-Portrait',
        vangogh_starry_night: 'Van Gogh — The Starry Night',
        vangogh_starry_rhone: 'Van Gogh — Starry Night over the Rhône',
        vangogh_sunflowers: 'Van Gogh — Sunflowers',
        vangogh_wheatfield: 'Van Gogh — Wheatfield with Crows',
        velazquez_lasmeninas: 'Velázquez — Las Meninas',
        velazquez_venus: 'Velázquez — Rokeby Venus',
        vermeer_astronomer: 'Vermeer — The Astronomer',
        vermeer_guitar: 'Vermeer — The Guitar Player',
        vermeer_milkmaid: 'Vermeer — The Milkmaid',
        vermeer_viewdelft: 'Vermeer — View of Delft',
        whistler_mother: 'Whistler — Arrangement in Grey and Black',
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

    function prevArt() {
        if (artOrder.length !== ART.length) shuffleArtOrder();
        artPos--;
        if (artPos < 0) artPos = artOrder.length - 1;
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

    function rotateArt(dir) {
        const next = dir === 'prev' ? prevArt() : nextArt();
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

    // Listen for remote commands broadcast by the :8771 server so a tablet
    // (or future big TV) can advance art on ALL displays at once.
    function listenForRemote() {
        const es = new EventSource('/api/events');
        // Wake the remote's screen when voice activity happens (power-remote
        // mode lets the display sleep; PTT/replies should be visible anyway).
        let wakeLock = null;
        async function wakeScreen() {
            try {
                if ('wakeLock' in navigator) {
                    if (!wakeLock || wakeLock.released) {
                        wakeLock = await navigator.wakeLock.request('screen');
                        wakeLock.addEventListener('release', () => { wakeLock = null; });
                    }
                    // Hold it only briefly: enough to show the interaction
                    setTimeout(() => { try { wakeLock && wakeLock.release(); } catch (e) {} }, 20000);
                }
            } catch (e) { /* wake lock optional (needs prior user gesture) */ }
        }
        es.onmessage = (ev) => {
            try {
                const cmd = JSON.parse(ev.data);
                if (cmd && cmd.type === 'command') {
                    if (cmd.action === 'voice_state' || cmd.action === 'voice_reply') wakeScreen();
                    if (cmd.action === 'next' || cmd.action === 'prev') rotateArt(cmd.action);
                    if (cmd.action === 'wake') setVoiceState('listening');
                    if (cmd.action === 'voice_state') {
                        showVoiceOverlay();
                        setVoiceState(cmd.state || 'listening');
                        setTranscript(cmd.text || '');
                    }
                    if (cmd.action === 'voice_reply') {
                        showVoiceOverlay();
                        setVoiceState('reply');
                        setTranscript(cmd.text || '');
                        scheduleOverlayHide();
                        scheduleIdleScrub();
                        if (cmd.audio) playReplyAudio(cmd.audio);
                    }
                    if (cmd.action === 'voice_state' && cmd.state === 'listening') {
                        setTranscript('');
                        scheduleIdleScrub();
                    }
                    if (cmd.action === 'voice_clear') {
                        hideVoiceOverlay();
                        setVoiceState('idle');
                        setTranscript('');
                    }
                    // ---- GA-Desk: 3-state surface (art ⇄ quick ⇄ desk) ----
                    if (cmd.action === 'desk_open') {
                        deskOpenState();
                    }
                    if (cmd.action === 'desk_close') {
                        closeDesk();
                    }
                }
            } catch (e) { /* ignore malformed */ }
        };
    }

    // ---- GA-Desk state machine -------------------------------------------
    // ART (ambient) ⇄ CAPTION (PTT quick query) ⇄ DESK (full user dashboard
    // via Hermes desktop over the kiosk / dashboard page on the TV).
    // desk_open: suspend art timers, show handoff card; the desktop switcher
    // (macOS: osascript bring-forward; TCL: dashboard URL swap) takes it from
    // here. desk_close: kill any timeout, resume art.
    let deskOpen = false;
    let deskTimeoutTimer = null;
    const DESK_IDLE_TIMEOUT_MS = 10 * 60 * 1000;   // 10 min default

    function deskOpenState() {
        deskOpen = true;
        // Suspend art rotation to keep the screen stable while working; the
        // desktop/dashboard will be fullscreen over this kiosk anyway.
        document.body.classList.add('desk-open');
        showVoiceOverlay();
        setVoiceState('reply');
        setTranscript('Desk starting… say "desk down" to return to the art.');
        scheduleOverlayHide(8000);
        scheduleIdleScrub(60000);
        clearTimeout(deskTimeoutTimer);
        deskTimeoutTimer = setTimeout(closeDesk, DESK_IDLE_TIMEOUT_MS);
        // Hook for the device-side switcher (install_andrea_kiosk env): the
        // TCL kiosk swaps to the dashboard URL; iMac fires an osascript to
        // bring Hermes desktop forward. Wired by the deploy script.
        try { if (window.gaDeskOpen) window.gaDeskOpen(); } catch (e) {}
    }

    function closeDesk() {
        deskOpen = false;
        clearTimeout(deskTimeoutTimer);
        document.body.classList.remove('desk-open');
        hideVoiceOverlay();
        setVoiceState('idle');
        setTranscript('');
        // Resume the art clock: trigger one rotation immediately.
        try { rotateArt(); } catch (e) {}
        try { if (window.gaDeskClose) window.gaDeskClose(); } catch (e) {}
    }
    window.gaDeskClose = null; // deploy hook: iMac switcher assigns handlers

    // ---- push-to-talk (device mic, hold-to-talk) ---------------------------
    // Each tablet records its OWN mic (HTTPS origin required for getUserMedia)
    // and posts to /api/voice: STT -> Jeeves /chat -> TTS. Reply caption goes
    // to ALL displays via SSE; reply audio plays on the device that talked.
    // Hold the mic button, speak, release = end of query. No wake word.
    let pttRecording = false;
    let pttStream = null;
    let pttRecorder = null;

    async function pttStart() {
        if (pttRecording) return;
        try {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                setTranscript('mic unavailable (need HTTPS)');
                return;
            }
            pttStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            pttRecorder = new MediaRecorder(pttStream);
            const chunks = [];
            pttRecorder.ondataavailable = (e) => chunks.push(e.data);
            pttRecorder.onstop = async () => {
                // Read mimeType BEFORE nulling (this exact order caused a
                // null-deref that silently killed the whole pipeline).
                const mimeType = pttRecorder.mimeType || 'audio/webm';
                pttStream.getTracks().forEach(t => t.stop());
                pttStream = null; pttRecorder = null;
                const blob = new Blob(chunks, { type: mimeType });
                const b64 = await new Promise((res) => {
                    const fr = new FileReader();
                    fr.onloadend = () => res(fr.result.split(',')[1]);
                    fr.readAsDataURL(blob);
                });
                if (blob.size < 6000) {   // tap, not speech — abort quietly
                    hideVoiceOverlay(); setVoiceState('idle'); return;
                }
                setVoiceState('thinking'); setTranscript('…');
                try {
                    const r = await fetch('/api/voice', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ audio_base64: b64 })
                    });
                    const j = await r.json();
                    if (j.ok && j.reply) {
                        showVoiceOverlay(); setVoiceState('reply');
                        setTranscript(j.reply);
                        scheduleOverlayHide(); scheduleIdleScrub();
                        if (j.audio) {
                            playReplyAudio(j.audio);
                        } else {
                            scheduleIdleScrub();
                        }
                    } else {
                        setTranscript(j.reply || '…');
                        scheduleOverlayHide(); scheduleIdleScrub();
                    }
                } catch (err) {
                    setTranscript('connection lost');
                    scheduleOverlayHide(); scheduleIdleScrub();
                }
            };
            pttRecorder.start();
            pttRecording = true;
            showVoiceOverlay(); setVoiceState('listening'); setTranscript('');
            const btn = document.getElementById('ptt-btn');
            if (btn) { btn.classList.add('recording'); btn.classList.add('visible'); }
            scheduleIdleScrub(60000);  // generous ceiling; release is the real end
        } catch (e) {
            setTranscript('mic denied — check WebView permission');
            scheduleOverlayHide(4000); scheduleIdleScrub();
        }
    }

    function pttStop() {
        if (!pttRecording) return;
        pttRecording = false;
        const btn = document.getElementById('ptt-btn');
        if (btn) {
            btn.classList.remove('recording');
            // Keep the controls surface up right after release (user is engaged);
            // it fades on the normal 4s cursor timer.
            btn.classList.add('visible');
        }
        scheduleIdleScrub();
        clearTimeout(cursorTimer);
        cursorTimer = setTimeout(hideCursor, 4000);
        try { pttRecorder.stop(); } catch (e) {}
    }

    function mountPttButton() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return; // no mic → no button
        const btn = document.createElement('button');
        btn.id = 'ptt-btn';
        btn.setAttribute('aria-label', 'Hold to talk');
        btn.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1"/><line x1="12" y1="18" x2="12" y2="22"/></svg>';
        const down = (e) => { e.preventDefault(); e.stopPropagation(); pttStart(); };
        const up = (e) => { e.preventDefault(); e.stopPropagation(); pttStop(); };
        btn.addEventListener('pointerdown', down);
        btn.addEventListener('pointerup', up);
        btn.addEventListener('pointercancel', up);
        btn.addEventListener('pointerleave', up);
        btn.addEventListener('contextmenu', (e) => e.preventDefault());
        document.body.appendChild(btn);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountPttButton);
    } else {
        mountPttButton();
    }

    function playReplyAudio(b64) {
        try {
            const audio = new Audio('data:audio/wav;base64,' + b64);
            audio.onended = () => { setTimeout(() => { endVoiceInteraction(); }, 4000); };
            audio.play().catch(() => { endVoiceInteraction(); });
        } catch (e) { /* playback optional */ }
    }

    // End-of-interaction cleanup: overlay gone, state idle, and the PTT button
    // returns to its hidden (burnin-safe) state unless the cursor is still up.
    function endVoiceInteraction() {
        hideVoiceOverlay();
        setVoiceState('idle');
        if (!cursorVisible) {
            const pttBtn = document.getElementById('ptt-btn');
            if (pttBtn) pttBtn.classList.remove('visible');
        }
    }

    let overlayHideTimer = null;
    function scheduleOverlayHide(ms) {
        clearTimeout(overlayHideTimer);
        overlayHideTimer = setTimeout(() => { endVoiceInteraction(); }, ms || 12000);
    }

    // Idle-scrub: if any voice state lingers (missed SSE reply, stale card),
    // force everything back to a clean idle after a generous ceiling.
    let idleScrubTimer = null;
    function scheduleIdleScrub(ms) {
        clearTimeout(idleScrubTimer);
        idleScrubTimer = setTimeout(() => {
            endVoiceInteraction();
            setTranscript('');
        }, ms || 25000);
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
        // Reveal PTT with the exit X (single tap = controls surface); it fades
        // with the same 4s timer. Burn-in: never shown while ambient.
        const pttBtn = document.getElementById('ptt-btn');
        if (pttBtn && navigator.mediaDevices) pttBtn.classList.add('visible');
        clearTimeout(cursorTimer);
        cursorTimer = setTimeout(hideCursor, 4000);
    }

    function hideCursor() {
        cursorVisible = false;
        document.body.style.cursor = 'none';
        const exitBtn = document.getElementById('exit-btn');
        if (exitBtn) exitBtn.style.opacity = '0';
        // PTT fades too — unless a recording is in flight (the recording
        // class pins visibility via CSS so the button never vanishes mid-hold).
        if (!pttRecording) {
            const pttBtn = document.getElementById('ptt-btn');
            if (pttBtn) pttBtn.classList.remove('visible');
        }
    }

    function quit() {
        // Try to close via window.close()
        window.close();

        // If that doesn't work (Chrome kiosk mode), go to the remote control
        // page instead of a blank screen, so the user is never stranded.
        setTimeout(() => {
            window.location.href = '/remote.html';
        }, 500);

        // Also try to signal the server
        try {
            fetch('/api/quit', {method: 'POST'});
        } catch (e) {}
    }

    // ---- Fullscreen (Android/Chrome: requires a user gesture) ----
    let fullscreenArmed = false;

    function enterFullscreen() {
        const el = document.documentElement;
        const req = (el.requestFullscreen ||
                     el.webkitRequestFullscreen ||
                     el.webkitEnterFullscreen ||
                     function () {});
        try { req.call(el); } catch (e) {}
    }

    function onFirstTap() {
        // Remove the one-shot gesture listeners.
        document.removeEventListener('pointerdown', onFirstTap);
        document.removeEventListener('touchstart', onFirstTap);
        // If we're not already fullscreen, enter it now (gesture satisfies Chrome).
        if (!document.fullscreenElement) enterFullscreen();
    }

    function initFullscreen() {
        if (document.fullscreenEnabled) {
            // Chrome on Android will ignore a fullscreen request without a user
            // gesture, so arm on the first touch/tap as well as trying on load.
            document.addEventListener('fullscreenchange', () => {
                fullscreenArmed = true;
            });
            document.addEventListener('pointerdown', onFirstTap);
            document.addEventListener('touchstart', onFirstTap);
            // Best-effort immediate enter (works on desktop + some tablets).
            enterFullscreen();
        }
    }

    function init() {
        // POWER MODE: battery-driven remotes (tablets) can't run full-bleed
        // artwork always-on — the crossfades + large JPEG decodes drain the
        // battery fast. Default = power-remote: screen near-black, no art
        // network loads, no 30s rotation; keep clock/weather/PTT. Powered
        // ambient screens (big TV, wall displays) load ?power=full for art.
        const powerFull = new URLSearchParams(location.search).get('power') === 'full';
        document.getElementById('art-backdrop').dataset.enabled = powerFull ? 'true' : 'false';

        // Clock every 10s in power mode (1s updates wake the GPU constantly);
        // clock text is HH:MM anyway in the bar, seconds hidden there.
        const clockMs = powerFull ? 1000 : 10000;

        // Initialize GENIUS TV brand visibility (start shown, end hidden)
        document.getElementById('brand-start').style.display = '';
        document.getElementById('brand-end').style.display = 'none';

        // Timers
        updateClock();
        setInterval(updateClock, clockMs);

        updateWeather();
        setInterval(updateWeather, 600000);

        if (powerFull) {
            const first = ART[0];
            document.getElementById('art-current').src = `art/${first}.jpg`;
            document.getElementById('art-title').textContent = ART_TITLES[first] || first;
            rotateArt();
            setInterval(rotateArt, 30000);
        } else {
            // Power-remote: no art title, dark backdrop via CSS class
            document.body.classList.add('power-remote');
            setInterval(permuteBar, 600000);
        }

        if (powerFull) {
            migrateBar();
            setInterval(migrateBar, 300000);
        }

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

        // Push-to-talk replaced double-tap: hold the mic button (PTT) instead.
        // Taps elsewhere stay reserved for the one-shot fullscreen arm.

        // Fullscreen: hide browser chrome for a clean ambient display.
        initFullscreen();

        // Remote-control plane: receive broadcast commands from :8771 server.
        listenForRemote();

        // Simulate wake word (for testing)
        console.log('Genius TV Chrome initialized');
    }

    return { init, quit, setVoiceState, setTranscript, showVoiceOverlay, hideVoiceOverlay, enterFullscreen };
})();

window.addEventListener('DOMContentLoaded', window.gtv.init);
