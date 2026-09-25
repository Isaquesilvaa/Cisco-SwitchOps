
(function () {
    "use strict";

    const sectionMeta = {
        dashboard: {
            title: "Dashboard",
            subtitle: "Visão geral do equipamento selecionado"
        },
        portas: {
            title: "Portas",
            subtitle: "Consulta e operação das interfaces"
        },
        dispositivos: {
            title: "Localizar dispositivo",
            subtitle: "Pesquisa de endereços MAC no parque"
        },
        vlans: {
            title: "VLANs",
            subtitle: "Gerenciamento de VLAN de acesso"
        },
        auditoria: {
            title: "Auditoria",
            subtitle: "Rastreabilidade das ações do SwitchOps"
        }
    };

    const navItems = Array.from(
        document.querySelectorAll(".nav-item[data-section]")
    );

    const views = Array.from(
        document.querySelectorAll(".view-section[data-view]")
    );

    const pageTitle = document.getElementById("page-title");
    const pageSubtitle = document.getElementById("page-subtitle");

    function activateSection(name, persist = true) {
        const exists = views.some(
            view => view.dataset.view === name
        );

        if (!exists) {
            name = "dashboard";
        }

        navItems.forEach(item => {
            item.classList.toggle(
                "active",
                item.dataset.section === name
            );
        });

        views.forEach(view => {
            view.classList.toggle(
                "active",
                view.dataset.view === name
            );
        });

        const meta = sectionMeta[name] || sectionMeta.dashboard;

        if (pageTitle) {
            pageTitle.textContent = meta.title;
        }

        if (pageSubtitle) {
            pageSubtitle.textContent = meta.subtitle;
        }

        if (persist) {
            sessionStorage.setItem(
                "switchops.activeSection",
                name
            );
        }

        if (name === "dashboard") {
            atualizarDashboardAoVivo();
        }
    }

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            activateSection(
                item.dataset.section
            );
        });
    });

    const rememberedSection =
        sessionStorage.getItem("switchops.activeSection");

    activateSection(
        rememberedSection || "dashboard",
        false
    );

    // ---------------------------------------------------------
    // Troca global de switch
    // ---------------------------------------------------------
    const globalSwitch =
        document.getElementById("global-switch");

    const portSwitch =
        document.getElementById("switch");

    const vlanSwitch =
        document.getElementById("vlan-switch");

    function changeSwitch(name) {
        const url = new URL(window.location.href);
        url.searchParams.set("switch", name);
        window.location.href = url.toString();
    }

    if (globalSwitch) {
        globalSwitch.addEventListener(
            "change",
            () => changeSwitch(globalSwitch.value)
        );
    }

    if (portSwitch) {
        portSwitch.addEventListener(
            "change",
            () => {
                sessionStorage.setItem(
                    "switchops.activeSection",
                    "portas"
                );

                changeSwitch(
                    portSwitch.value
                );
            }
        );
    }

    if (vlanSwitch) {
        vlanSwitch.addEventListener(
            "change",
            () => {
                sessionStorage.setItem(
                    "switchops.activeSection",
                    "vlans"
                );

                changeSwitch(
                    vlanSwitch.value
                );
            }
        );
    }

    // ---------------------------------------------------------
    // Mantém o usuário na tela da ação após POST
    // ---------------------------------------------------------
    const formPorta = document.getElementById("form-porta");
    const formVlan = document.getElementById("form-vlan");
    const formMac = document.getElementById("form-mac");

    if (formPorta) {
        formPorta.addEventListener("submit", event => {
            sessionStorage.setItem(
                "switchops.activeSection",
                "portas"
            );

            const operacao =
                event.submitter?.value || "";

            if (
                operacao === "desligar"
                || operacao === "ligar"
                || operacao === "sticky"
            ) {
                sessionStorage.setItem(
                    "switchops.portBurst",
                    "1"
                );
            }

            showLoading(
                "Executando operação no switch..."
            );
        });
    }

    if (formVlan) {
        formVlan.addEventListener("submit", () => {
            sessionStorage.setItem(
                "switchops.activeSection",
                "vlans"
            );

            showLoading(
                "Validando e aplicando a VLAN..."
            );
        });
    }

    if (formMac) {
        formMac.addEventListener("submit", () => {
            sessionStorage.setItem(
                "switchops.activeSection",
                "dispositivos"
            );

            showLoading(
                "Procurando dispositivo nos switches..."
            );
        });
    }

    // ---------------------------------------------------------
    // Loading
    // ---------------------------------------------------------
    function showLoading(text) {
        const overlay =
            document.getElementById("loading-dialog");

        const label =
            document.getElementById("loading-text");

        if (label && text) {
            label.textContent = text;
        }

        if (overlay) {
            overlay.classList.add("show");
        }
    }

    // ---------------------------------------------------------
    // Confirmação de shutdown
    // ---------------------------------------------------------
    window.confirmarDesligamento = function () {
        const switchSelect =
            document.getElementById("switch");

        const portaSelect =
            document.getElementById("porta");

        if (!switchSelect || !portaSelect) {
            return true;
        }

        return window.confirm(
            "Tem certeza que deseja desligar "
            + switchSelect.value
            + " / "
            + portaSelect.value
            + "?"
        );
    };

    // ---------------------------------------------------------
    // Dashboard - métricas via API
    // ---------------------------------------------------------
    let healthLoaded = false;
    let healthLoading = false;
    let healthTimer = null;
    const HEALTH_INTERVAL_MS = 5000;

    function setMetric(id, value) {
        const element = document.getElementById(id);

        if (element) {
            element.textContent = value;
        }
    }

    function setMeter(id, value) {
        const element = document.getElementById(id);

        if (!element) {
            return;
        }

        const safeValue = Math.max(
            0,
            Math.min(
                100,
                Number(value) || 0
            )
        );

        element.style.width = safeValue + "%";
    }

    function setTemperature(value, state) {
        const fan = document.getElementById(
            "temperature-fan"
        );

        const status = document.getElementById(
            "temp-status"
        );

        if (!fan) {
            return;
        }

        fan.classList.remove(
            "fan-neutral",
            "fan-cool",
            "fan-warm",
            "fan-hot"
        );

        if (value !== null && value !== undefined) {
            setMetric(
                "metric-temp",
                value + "°C"
            );

            if (value <= 45) {
                fan.classList.add("fan-cool");

                if (status) {
                    status.textContent = "temperatura normal";
                }

            } else if (value <= 60) {
                fan.classList.add("fan-warm");

                if (status) {
                    status.textContent = "atenção à temperatura";
                }

            } else {
                fan.classList.add("fan-hot");

                if (status) {
                    status.textContent = "temperatura elevada";
                }
            }

            return;
        }

        if (state === "OK") {
            fan.classList.add("fan-cool");
            setMetric("metric-temp", "OK");

            if (status) {
                status.textContent =
                    "estado térmico normal; IOS não informou graus";
            }

            return;
        }

        if (state === "WARNING") {
            fan.classList.add("fan-warm");
            setMetric("metric-temp", "ALERTA");

            if (status) {
                status.textContent =
                    "sensor informa estado de atenção";
            }

            return;
        }

        if (state === "CRITICAL") {
            fan.classList.add("fan-hot");
            setMetric("metric-temp", "CRÍTICO");

            if (status) {
                status.textContent =
                    "sensor informa temperatura crítica";
            }

            return;
        }

        fan.classList.add("fan-neutral");
        setMetric("metric-temp", "N/A");

        if (status) {
            status.textContent =
                "este IOS/modelo não expôs temperatura pela CLI";
        }
    }

    async function loadHealth(force) {
        if (healthLoading) {
            return;
        }

        if (healthLoaded && !force) {
            return;
        }

        const selectedSwitch =
            window.SWITCHOPS?.selectedSwitch;

        if (!selectedSwitch) {
            return;
        }

        healthLoading = true;

        const note =
            document.getElementById("health-message");

        if (note) {
            note.textContent =
                "Consultando métricas do equipamento...";
        }

        try {
            const response = await fetch(
                "/api/dashboard/"
                + encodeURIComponent(selectedSwitch),
                {
                    headers: {
                        "Accept": "application/json"
                    }
                }
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.erro || "Falha ao consultar métricas."
                );
            }

            setMetric(
                "metric-cpu",
                data.cpu === null ? "N/A" : data.cpu + "%"
            );

            setMeter(
                "meter-cpu",
                data.cpu
            );

            setMetric(
                "metric-memory",
                data.memoria === null
                    ? "N/A"
                    : data.memoria + "%"
            );

            setMeter(
                "meter-memory",
                data.memoria
            );

            setTemperature(
                data.temperatura,
                data.temperatura_estado
            );

            setMetric(
                "metric-uptime",
                data.uptime || "N/A"
            );

            if (note) {
                const agora = new Date().toLocaleTimeString(
                    "pt-BR",
                    {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit"
                    }
                );

                note.textContent = data.erro
                    ? "Algumas métricas não puderam ser consultadas: " + data.erro
                    : "Atualização automática ativa · última leitura " + agora + " · portas ~1 s · métricas ~5 s";
            }

            healthLoaded = true;

        } catch (error) {
            setMetric("metric-cpu", "N/A");
            setMetric("metric-memory", "N/A");
            setTemperature(null, null);
            setMetric("metric-uptime", "N/A");

            if (note) {
                note.textContent =
                    "Não foi possível atualizar as métricas: "
                    + error.message;
            }

        } finally {
            healthLoading = false;
        }
    }


    // ---------------------------------------------------------
    // Dashboard dinâmico via polling
    // ---------------------------------------------------------
    let livePollTimer = null;
    let livePortTimer = null;
    let livePollingBusy = false;
    let livePortBusy = false;

    const PORT_REFRESH_MS = 1000;
    const HEALTH_REFRESH_MS = 5000;
function setText(id, value) {
        const element = document.getElementById(id);

        if (element) {
            element.textContent = value;
        }
    }

    function setLiveBadge(state, text) {
        const badge = document.getElementById(
            "live-stream-badge"
        );

        if (!badge) {
            return;
        }

        badge.classList.remove(
            "online",
            "offline",
            "connecting"
        );

        badge.classList.add(state);

        const textNode = Array.from(
            badge.childNodes
        ).find(
            node => node.nodeType === Node.TEXT_NODE
        );

        if (textNode) {
            textNode.textContent = " " + text;
        } else {
            badge.appendChild(
                document.createTextNode(" " + text)
            );
        }
    }

    function updateConnectionPill(online) {
        const pill = document.getElementById(
            "live-connection-pill"
        );

        if (!pill) {
            return;
        }

        pill.classList.toggle(
            "offline",
            !online
        );

        const textNode = Array.from(
            pill.childNodes
        ).find(
            node => node.nodeType === Node.TEXT_NODE
        );

        if (textNode) {
            textNode.textContent = online
                ? " Rede interna"
                : " Sem resposta";
        }
    }

    function updatePortSummary(portas) {
        if (!Array.isArray(portas)) {
            return;
        }

        const total = portas.length;
        const up = portas.filter(
            porta => porta.estado === "connected"
        ).length;
        const trunks = portas.filter(
            porta => porta.trunk
        ).length;
        const down = total - up;

        setText("live-portas-up", up);
        setText("summary-up", up);
        setText("summary-down", down);
        setText("summary-trunk", trunks);
        setText("summary-total", total);

        const ring = document.getElementById(
            "live-port-ring"
        );

        if (ring) {
            const percent = total
                ? Math.round(up * 100 / total)
                : 0;

            ring.style.setProperty(
                "--up",
                percent
            );
        }
    }

    function updatePhysicalPorts(portas) {
        if (!Array.isArray(portas)) {
            return;
        }

        const classes = [
            "connected",
            "notconnect",
            "disabled",
            "err-disabled",
            "inactive",
            "trunk"
        ];

        portas.forEach(porta => {
            const escaped = window.CSS && CSS.escape
                ? CSS.escape(porta.porta)
                : porta.porta.replace(/"/g, "\\\"");

            const nodes = document.querySelectorAll(
                '.catalyst-port[data-port="'
                + escaped
                + '"], '
                + '.switch3d-port[data-live-port="'
                + escaped
                + '"]'
            );

            nodes.forEach(node => {
                classes.forEach(
                    cls => node.classList.remove(cls)
                );

                if (porta.estado) {
                    node.classList.add(porta.estado);
                }

                if (porta.trunk) {
                    node.classList.add("trunk");
                }

                node.title = [
                    porta.porta,
                    porta.nome || "-",
                    porta.estado || "-",
                    "VLAN " + (porta.vlan || "-"),
                    porta.velocidade || "-"
                ].join(" | ");
            });
        });
    }

    function updateLiveDashboard(data) {
        if (!data) {
            return;
        }

        setMetric(
            "metric-cpu",
            data.cpu === null || data.cpu === undefined
                ? "N/A"
                : data.cpu + "%"
        );
        setMeter("meter-cpu", data.cpu);

        setMetric(
            "metric-memory",
            data.memoria === null || data.memoria === undefined
                ? "N/A"
                : data.memoria + "%"
        );
        setMeter("meter-memory", data.memoria);

        setTemperature(
            data.temperatura,
            data.temperatura_estado
        );

        setMetric(
            "metric-uptime",
            data.uptime || "N/A"
        );

        updatePortSummary(data.portas);
        updatePhysicalPorts(data.portas);
        updateConnectionPill(Boolean(data.online));

        const note = document.getElementById(
            "health-message"
        );

        if (data.online) {
            setLiveBadge("online", "ao vivo");

            if (note) {
                const agora = new Date().toLocaleTimeString(
                    "pt-BR",
                    {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit"
                    }
                );

                note.textContent =
                    "Atualização automática ativa · última leitura "
                    + agora
                    + " · portas ~1 s · métricas ~5 s";
            }
        } else {
            setLiveBadge("offline", "sem resposta");

            if (note) {
                note.textContent =
                    "Não foi possível atualizar o switch."
                    + (data.erro ? " " + data.erro : "");
            }
        }
    }

    const lastPortState = new Map();
    let burstPortTimer = null;
    let burstPortStopTimer = null;

    function registrarMudancasDePorta(portas) {
        if (!Array.isArray(portas)) {
            return;
        }

        portas.forEach(porta => {
            const key = porta.porta;
            const atual = [
                porta.estado || "",
                porta.trunk ? "1" : "0",
                porta.vlan || ""
            ].join("|");

            const anterior = lastPortState.get(key);

            if (
                anterior !== undefined
                && anterior !== atual
            ) {
                const escaped = window.CSS && CSS.escape
                    ? CSS.escape(porta.porta)
                    : porta.porta.replace(/"/g, "\\\"");

                document.querySelectorAll(
                    '.switch3d-port[data-live-port="'
                    + escaped
                    + '"]'
                ).forEach(node => {
                    node.classList.remove("status-flash");

                    // força reflow para reiniciar o feedback visual
                    void node.offsetWidth;

                    node.classList.add("status-flash");

                    setTimeout(
                        () => node.classList.remove("status-flash"),
                        220
                    );
                });
            }

            lastPortState.set(
                key,
                atual
            );
        });
    }

    function iniciarBurstDePortas() {
        if (burstPortTimer) {
            clearInterval(burstPortTimer);
        }

        if (burstPortStopTimer) {
            clearTimeout(burstPortStopTimer);
        }

        atualizarPortasAoVivo();

        burstPortTimer = setInterval(
            atualizarPortasAoVivo,
            250
        );

        burstPortStopTimer = setTimeout(
            () => {
                if (burstPortTimer) {
                    clearInterval(burstPortTimer);
                    burstPortTimer = null;
                }

                sessionStorage.removeItem(
                    "switchops.portBurst"
                );
            },
            4000
        );
    }


    async function atualizarPortasAoVivo() {
        if (livePortBusy || document.hidden) {
            return;
        }

        const selectedSwitch =
            window.SWITCHOPS?.selectedSwitch;

        if (!selectedSwitch) {
            return;
        }

        livePortBusy = true;

        try {
            const response = await fetch(
                "/api/live-ports/"
                + encodeURIComponent(
                    selectedSwitch
                ),
                {
                    headers: {
                        "Accept": "application/json"
                    },
                    cache: "no-store"
                }
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.erro
                    || "Falha ao consultar portas."
                );
            }

            registrarMudancasDePorta(
                data.portas
            );

            updatePortSummary(
                data.portas
            );

            updatePhysicalPorts(
                data.portas
            );

            updateConnectionPill(
                Boolean(
                    data.online
                )
            );

        } catch (error) {
            updateConnectionPill(false);

        } finally {
            livePortBusy = false;
        }
    }


    async function atualizarDashboardAoVivo() {
        if (livePollingBusy) {
            return;
        }

        const selectedSwitch =
            window.SWITCHOPS?.selectedSwitch;

        if (!selectedSwitch) {
            return;
        }

        livePollingBusy = true;
        setLiveBadge("connecting", "atualizando...");

        try {
            const response = await fetch(
                "/api/live/"
                + encodeURIComponent(selectedSwitch),
                {
                    headers: {
                        "Accept": "application/json"
                    },
                    cache: "no-store"
                }
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.erro || "Falha ao consultar dados."
                );
            }

            updateLiveDashboard(data);

        } catch (error) {
            setLiveBadge("offline", "sem resposta");
            updateConnectionPill(false);

            const note = document.getElementById(
                "health-message"
            );

            if (note) {
                note.textContent =
                    "Falha na atualização automática: "
                    + error.message;
            }
        } finally {
            livePollingBusy = false;
        }
    }

    function pararAtualizacaoAutomatica() {
        if (livePortTimer) {
            clearInterval(livePortTimer);
            livePortTimer = null;
        }

        if (livePollTimer) {
            clearInterval(livePollTimer);
            livePollTimer = null;
        }

        if (burstPortTimer) {
            clearInterval(burstPortTimer);
            burstPortTimer = null;
        }

        if (burstPortStopTimer) {
            clearTimeout(burstPortStopTimer);
            burstPortStopTimer = null;
        }
    }

    function iniciarAtualizacaoAutomatica() {
        pararAtualizacaoAutomatica();

        // Primeira leitura assim que a tela entra.
        atualizarPortasAoVivo();
        atualizarDashboardAoVivo();

        // Estado das portas quase em tempo real.
        livePortTimer = setInterval(
            atualizarPortasAoVivo,
            PORT_REFRESH_MS
        );

        // Saúde do switch em frequência menor.
        livePollTimer = setInterval(
            atualizarDashboardAoVivo,
            HEALTH_REFRESH_MS
        );
    }

    const refreshHealth = document.getElementById(
        "refresh-health"
    );

    if (refreshHealth) {
        refreshHealth.addEventListener(
            "click",
            async () => {
                await Promise.all([
                    atualizarPortasAoVivo(),
                    atualizarDashboardAoVivo()
                ]);
            }
        );
    }

    document.addEventListener(
        "visibilitychange",
        () => {
            if (document.hidden) {
                pararAtualizacaoAutomatica();
            } else {
                iniciarAtualizacaoAutomatica();
            }
        }
    );

    window.addEventListener(
        "beforeunload",
        pararAtualizacaoAutomatica
    );

    iniciarAtualizacaoAutomatica();

    if (
        sessionStorage.getItem(
            "switchops.portBurst"
        ) === "1"
    ) {
        iniciarBurstDePortas();
    }



    // ---------------------------------------------------------
    // Modelo 3D girável do switch
    // Dashboard e área de Portas podem ter instâncias independentes.
    // ---------------------------------------------------------
    function initSwitch3D() {
        const stages = document.querySelectorAll(
            "[data-switch3d-stage]"
        );

        stages.forEach(stage => {
            if (stage.dataset.switch3dReady === "1") {
                return;
            }

            const card = stage.closest(".switch3d-card");
            const object = stage.querySelector(
                "[data-switch3d-object]"
            );

            if (!card || !object) {
                return;
            }

            stage.dataset.switch3dReady = "1";

            let rotationX = -8;
            let rotationY = -12;

            const portRows = Number(
                card.dataset.portRows || 2
            );

            let zoom = portRows <= 2
                ? 1
                : portRows === 3
                    ? .96
                    : .90;

            let dragging = false;
            let startX = 0;
            let startY = 0;
            let startRotationX = rotationX;
            let startRotationY = rotationY;

            const clamp = (value, min, max) =>
                Math.min(max, Math.max(min, value));

            function renderSwitch3D(animated = true) {
                stage.classList.toggle(
                    "dragging",
                    !animated
                );

                object.style.transform =
                    "scale(" + zoom + ") "
                    + "rotateX(" + rotationX + "deg) "
                    + "rotateY(" + rotationY + "deg)";
            }

            function selectView(name) {
                const baseZoom = portRows <= 2
                    ? 1
                    : portRows === 3
                        ? .96
                        : .90;

                const presets = {
                    front: {
                        x: 0,
                        y: 0,
                        z: Math.min(1.06, baseZoom + .06)
                    },
                    back: {
                        x: 0,
                        y: 180,
                        z: baseZoom
                    },
                    top: {
                        x: -90,
                        y: 0,
                        z: baseZoom * .90
                    },
                    left: {
                        x: 0,
                        y: 90,
                        z: baseZoom * .94
                    },
                    right: {
                        x: 0,
                        y: -90,
                        z: baseZoom * .94
                    }
                };

                const preset = presets[name];

                if (!preset) {
                    return;
                }

                rotationX = preset.x;
                rotationY = preset.y;
                zoom = preset.z;

                renderSwitch3D(true);

                card.querySelectorAll(
                    "[data-switch-view]"
                ).forEach(button => {
                    button.classList.toggle(
                        "active",
                        button.dataset.switchView === name
                    );
                });
            }

            stage.addEventListener(
                "pointerdown",
                event => {
                    dragging = true;

                    card.querySelectorAll(
                        "[data-switch-view]"
                    ).forEach(button => {
                        button.classList.remove(
                            "active"
                        );
                    });

                    startX = event.clientX;
                    startY = event.clientY;

                    startRotationX = rotationX;
                    startRotationY = rotationY;

                    stage.setPointerCapture(
                        event.pointerId
                    );

                    stage.classList.add(
                        "dragging"
                    );
                }
            );

            stage.addEventListener(
                "pointermove",
                event => {
                    if (!dragging) {
                        return;
                    }

                    const dx =
                        event.clientX - startX;

                    const dy =
                        event.clientY - startY;

                    rotationY =
                        startRotationY
                        + dx * .38;

                    rotationX = clamp(
                        startRotationX
                        - dy * .28,
                        -88,
                        88
                    );

                    renderSwitch3D(false);
                }
            );

            function finishDrag(event) {
                if (!dragging) {
                    return;
                }

                dragging = false;

                stage.classList.remove(
                    "dragging"
                );

                if (
                    event
                    && stage.hasPointerCapture(
                        event.pointerId
                    )
                ) {
                    stage.releasePointerCapture(
                        event.pointerId
                    );
                }
            }

            stage.addEventListener(
                "pointerup",
                finishDrag
            );

            stage.addEventListener(
                "pointercancel",
                finishDrag
            );

            stage.addEventListener(
                "wheel",
                event => {
                    event.preventDefault();

                    card.querySelectorAll(
                        "[data-switch-view]"
                    ).forEach(button => {
                        button.classList.remove(
                            "active"
                        );
                    });

                    zoom = clamp(
                        zoom
                        + (
                            event.deltaY < 0
                                ? .06
                                : -.06
                        ),
                        .62,
                        1.22
                    );

                    renderSwitch3D(true);
                },
                {
                    passive: false
                }
            );

            stage.addEventListener(
                "keydown",
                event => {
                    card.querySelectorAll(
                        "[data-switch-view]"
                    ).forEach(button => {
                        button.classList.remove(
                            "active"
                        );
                    });

                    if (
                        event.key
                        === "ArrowLeft"
                    ) {
                        rotationY -= 10;

                    } else if (
                        event.key
                        === "ArrowRight"
                    ) {
                        rotationY += 10;

                    } else if (
                        event.key
                        === "ArrowUp"
                    ) {
                        rotationX = clamp(
                            rotationX - 8,
                            -88,
                            88
                        );

                    } else if (
                        event.key
                        === "ArrowDown"
                    ) {
                        rotationX = clamp(
                            rotationX + 8,
                            -88,
                            88
                        );

                    } else {
                        return;
                    }

                    event.preventDefault();

                    renderSwitch3D(true);
                }
            );

            card.querySelectorAll(
                "[data-switch-view]"
            ).forEach(button => {
                button.addEventListener(
                    "click",
                    () => {
                        selectView(
                            button.dataset.switchView
                        );
                    }
                );
            });

            selectView("front");
        });
    }

    initSwitch3D();

})();
