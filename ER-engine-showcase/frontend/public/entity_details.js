"use strict";

/*
 * This page currently uses demonstration data.
 *
 * Later, index.html can store the backend response with:
 *
 * sessionStorage.setItem(
 *     "erEntityDetails",
 *     JSON.stringify({
 *         entities: result.entities,
 *         comparisons: result.comparisons,
 *     })
 * );
 *
 * This page automatically uses that stored data when available.
 */

/* =========================================================
   PLACEHOLDER IMAGES
   ========================================================= */

function makePlaceholderImage(label, start, end) {
    const svg = `
        <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800">
            <defs>
                <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stop-color="${start}" />
                    <stop offset="100%" stop-color="${end}" />
                </linearGradient>
            </defs>
            <rect width="1200" height="800" fill="url(#g)" />
            <path
                d="M0 630 L250 390 L470 590 L730 280 L1200 650 L1200 800 L0 800 Z"
                fill="rgba(255,255,255,0.18)"
            />
            <circle cx="930" cy="190" r="95" fill="rgba(255,255,255,0.22)" />
            <text
                x="600"
                y="420"
                text-anchor="middle"
                font-family="Arial, sans-serif"
                font-size="60"
                font-weight="700"
                fill="white"
            >
                ${label}
            </text>
        </svg>
    `;

    return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

const placeholderSets = {
    flatA: [
        makePlaceholderImage("Living room", "#496b84", "#c7d6df"),
        makePlaceholderImage("Kitchen", "#7c604d", "#d9c8b9"),
        makePlaceholderImage("Bedroom", "#50636f", "#c7ced3"),
        makePlaceholderImage("Bathroom", "#4d7880", "#c3e0e4"),
        makePlaceholderImage("Building", "#5c6278", "#d4d7e5"),
        makePlaceholderImage("Hallway", "#765f4c", "#d7cabb"),
    ],
    flatB: [
        makePlaceholderImage("Main room", "#445f75", "#bbcbd7"),
        makePlaceholderImage("Dining area", "#6f5845", "#d9c0a9"),
        makePlaceholderImage("Bedroom", "#4a596a", "#bdc9d6"),
        makePlaceholderImage("Balcony", "#446f63", "#bed8cf"),
        makePlaceholderImage("Exterior", "#646176", "#d1cddd"),
    ],
    flatC: [
        makePlaceholderImage("Studio", "#4c6e86", "#c8d8e4"),
        makePlaceholderImage("Kitchenette", "#7b634c", "#decbb8"),
        makePlaceholderImage("Sleeping area", "#54606f", "#ccd1d8"),
        makePlaceholderImage("Bathroom", "#4d7783", "#c1dde3"),
    ],
    flatD: [
        makePlaceholderImage("Living room", "#526b7c", "#c8d4dc"),
        makePlaceholderImage("Kitchen", "#71604e", "#d7c7b9"),
        makePlaceholderImage("Bedroom", "#555f6c", "#cad0d6"),
        makePlaceholderImage("Terrace", "#526f61", "#c5dbd0"),
        makePlaceholderImage("Facade", "#676474", "#d5d2dc"),
    ],
};


/* =========================================================
   DEMONSTRATION DATA
   ========================================================= */


/* =========================================================
   DATA NORMALISATION
   ========================================================= */

function readStoredEntityData() {
    const stored = sessionStorage.getItem("erEntityDetails");

    if (!stored) {
        return null;
    }

    try {
        const parsed = JSON.parse(stored);

        if (!Array.isArray(parsed.entities)) {
            return null;
        }

        const sharedComparisons = Array.isArray(parsed.comparisons)
            ? parsed.comparisons
            : [];

        return parsed.entities.map((entity) => {
            const listingIds = getListingIds(entity);

            const comparisons = sharedComparisons.filter((comparison) => {
                const first = String(comparison.ID_1 ?? comparison.id_1 ?? "");
                const second = String(comparison.ID_2 ?? comparison.id_2 ?? "");

                return listingIds.includes(first) || listingIds.includes(second);
            });

            return {
                ...entity,
                comparisons,
                cutoff:
                    Number(entity.cutoff) ||
                    Number(comparisons[0]?.rf2_threshold) ||
                    0.51,
                agreement: Array.isArray(entity.agreement)
                    ? entity.agreement
                    : deriveAgreement(entity.listings || []),
            };
        });
    } catch (error) {
        console.warn("Stored entity details could not be parsed.", error);
        return null;
    }
}

const entities = readStoredEntityData() || [];

const entitySelector = document.getElementById("entity-selector");
const entityContent = document.getElementById("entity-content");
const lightbox = document.getElementById("image-lightbox");
const lightboxImage = document.getElementById("lightbox-image");
const lightboxCaption = document.getElementById("lightbox-caption");
const closeLightboxButton = document.getElementById("close-lightbox");

let selectedEntityId = getInitialEntityId();
let graphState = null;

/* =========================================================
   FORMATTERS
   ========================================================= */

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function humanize(value) {
    return String(value ?? "Unavailable")
        .replaceAll("_", " ")
        .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatEntityTitle(entityId) {
    const match = String(entityId).match(/(\d+)$/);
    const number = match ? match[1].padStart(3, "0") : "001";
    return `Entity ${number}`;
}

function formatNumber(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return value ?? "Unavailable";
    }

    return new Intl.NumberFormat("en-US").format(number);
}

function formatMoney(value) {
    const number = Number(value);

    return Number.isFinite(number)
        ? `${formatNumber(number)} CZK`
        : "Unavailable";
}

function formatProbability(value) {
    const number = Number(value);

    return Number.isFinite(number)
        ? `${(number * 100).toFixed(2)}%`
        : "Unavailable";
}

function formatDistance(value, cutoff) {
    const probability = Number(value);
    const threshold = Number(cutoff);

    if (!Number.isFinite(probability) || !Number.isFinite(threshold)) {
        return "Unavailable";
    }

    return `${(Math.abs(probability - threshold) * 100).toFixed(2)}%`;
}

function average(values) {
    const numeric = values.map(Number).filter(Number.isFinite);

    if (numeric.length === 0) {
        return null;
    }

    return numeric.reduce((sum, value) => sum + value, 0) / numeric.length;
}

function minimum(values) {
    const numeric = values.map(Number).filter(Number.isFinite);
    return numeric.length ? Math.min(...numeric) : null;
}

function maximum(values) {
    const numeric = values.map(Number).filter(Number.isFinite);
    return numeric.length ? Math.max(...numeric) : null;
}

/* =========================================================
   ENTITY CALCULATIONS
   ========================================================= */

function getListingIds(entity) {
    if (Array.isArray(entity.listing_ids)) {
        return entity.listing_ids.map(String);
    }

    return (entity.listings || [])
        .map((listing) => listing.ID)
        .filter(Boolean)
        .map(String);
}

function getProbability(comparison) {
    const value =
        comparison.rf2_probability ??
        comparison.prob_duplicate_rf2;

    const probability = Number(value);
    return Number.isFinite(probability) ? probability : null;
}

function getRelevantComparisons(entity) {
    const listingIds = new Set(getListingIds(entity));
    const comparisons = entity.comparisons || [];

    if (listingIds.size > 1) {
        const internal = comparisons.filter((comparison) => {
            const first = String(comparison.ID_1 ?? comparison.id_1 ?? "");
            const second = String(comparison.ID_2 ?? comparison.id_2 ?? "");
            return listingIds.has(first) && listingIds.has(second);
        });

        if (internal.length) {
            return internal;
        }
    }

    return comparisons.filter((comparison) => {
        const first = String(comparison.ID_1 ?? comparison.id_1 ?? "");
        const second = String(comparison.ID_2 ?? comparison.id_2 ?? "");
        return listingIds.has(first) || listingIds.has(second);
    });
}

function getEntityMetrics(entity) {
    const listings = entity.listings || [];
    const comparisons = getRelevantComparisons(entity);
    const probabilities = comparisons
        .map(getProbability)
        .filter((value) => value !== null);

    const cutoff = Number(entity.cutoff) || 0.51;
    const possibleInternalEdges =
        listings.length > 1
            ? (listings.length * (listings.length - 1)) / 2
            : 0;

    const internalIds = new Set(getListingIds(entity));
    const positiveInternalEdges = comparisons.filter((comparison) => {
        const first = String(comparison.ID_1 ?? comparison.id_1 ?? "");
        const second = String(comparison.ID_2 ?? comparison.id_2 ?? "");
        const probability = getProbability(comparison);

        return (
            internalIds.has(first) &&
            internalIds.has(second) &&
            probability !== null &&
            probability >= cutoff
        );
    }).length;

    const agencies = new Set(
        listings.map((listing) => listing.Agency).filter(Boolean)
    );

    return {
        listingCount: listings.length,
        averageProbability: average(probabilities),
        minimumProbability: minimum(probabilities),
        maximumProbability: maximum(probabilities),
        positiveEdges: positiveInternalEdges,
        negativeEdges: comparisons.filter((comparison) => {
            const probability = getProbability(comparison);
            return probability !== null && probability < cutoff;
        }).length,
        graphDensity:
            possibleInternalEdges > 0
                ? positiveInternalEdges / possibleInternalEdges
                : 0,
        agencyCount: agencies.size,
        cutoff,
    };
}

function deriveAgreement(listings) {
    if (!Array.isArray(listings) || listings.length === 0) {
        return [];
    }

    const fields = [
        ["Street", "Street"],
        ["Type", "Type"],
        ["Net area", "Net.Area"],
        ["Price", "Price"],
        ["Agency", "Agency"],
    ];

    return fields.map(([label, key]) => {
        const values = listings
            .map((listing) => listing[key])
            .filter((value) => value !== null && value !== undefined && value !== "");

        const unique = [...new Set(values.map(String))];
        const exact = unique.length <= 1;

        return {
            attribute: label,
            value: unique.join(" / ") || "Unavailable",
            status: exact ? "match" : "close",
            explanation: exact ? "Exact agreement" : "Values differ across listings",
        };
    });
}

function getInitialEntityId() {
    const queryId = new URLSearchParams(window.location.search).get("entity");

    if (queryId && entities.some((entity) => entity.entity_id === queryId)) {
        return queryId;
    }

    return entities[0]?.entity_id || null;
}

/* =========================================================
   STABLE IMAGE SELECTION
   ========================================================= */

function stringHash(value) {
    let hash = 2166136261;

    for (const character of String(value)) {
        hash ^= character.charCodeAt(0);
        hash = Math.imul(hash, 16777619);
    }

    return hash >>> 0;
}

function seededRandom(seed) {
    let state = seed >>> 0;

    return function random() {
        state += 0x6D2B79F5;
        let value = state;
        value = Math.imul(value ^ (value >>> 15), value | 1);
        value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
        return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
    };
}

function selectStableRandomImages(listing, maximumImages = 5) {
    const images = Array.isArray(listing["Image.URLs"])
        ? [...new Set(listing["Image.URLs"].filter(Boolean))]
        : [];

    const random = seededRandom(stringHash(listing.ID));

    for (let index = images.length - 1; index > 0; index -= 1) {
        const swapIndex = Math.floor(random() * (index + 1));
        [images[index], images[swapIndex]] = [images[swapIndex], images[index]];
    }

    return images.slice(0, maximumImages);
}

/* =========================================================
   SELECTOR AND OVERVIEW
   ========================================================= */

const entitySelectorPrev = document.getElementById(
    "entity-selector-prev"
);

const entitySelectorNext = document.getElementById(
    "entity-selector-next"
);

function renderEntitySelector() {
    entitySelector.innerHTML = entities
        .map((entity) => {
            const metrics = getEntityMetrics(entity);
            const selected = entity.entity_id === selectedEntityId;

            return `
                <button
                    class="entity-selector-button ${selected ? "is-selected" : ""}"
                    type="button"
                    data-entity-id="${escapeHtml(entity.entity_id)}"
                    aria-pressed="${selected}"
                >
                    <span class="selector-title">
                        ${escapeHtml(formatEntityTitle(entity.entity_id))}
                    </span>

                    <span class="selector-meta">
                        ${metrics.listingCount}
                        ${metrics.listingCount === 1 ? "listing" : "listings"}
                    </span>

                    <span class="selector-probability">
                        ${escapeHtml(formatProbability(metrics.averageProbability))}
                        average
                    </span>

                    ${
                        selected
                            ? '<span class="selector-selected">Selected</span>'
                            : ""
                    }
                </button>
            `;
        })
        .join("");
}

function getEntitySelectorScrollAmount() {
    const firstCard = entitySelector.querySelector(
        ".entity-selector-button"
    );

    if (!firstCard) {
        return 220;
    }

    const styles = window.getComputedStyle(entitySelector);
    const gap = Number.parseFloat(styles.columnGap || styles.gap) || 14;

    return firstCard.getBoundingClientRect().width + gap;
}


function updateEntitySelectorArrows() {
    const maxScroll =
        entitySelector.scrollWidth -
        entitySelector.clientWidth;

    entitySelectorPrev.disabled =
        entitySelector.scrollLeft <= 2;

    entitySelectorNext.disabled =
        entitySelector.scrollLeft >= maxScroll - 2;
}


function scrollEntitySelector(direction) {
    const amount =
        getEntitySelectorScrollAmount() * direction;

    entitySelector.scrollBy({
        left: amount,
        behavior: "smooth",
    });
}


function scrollSelectedEntityIntoView() {
    const selectedButton = entitySelector.querySelector(
        ".entity-selector-button.is-selected"
    );

    if (!selectedButton) {
        return;
    }

    selectedButton.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
        inline: "center",
    });
}

entitySelectorPrev?.addEventListener("click", () => {
    scrollEntitySelector(-1);
});


entitySelectorNext?.addEventListener("click", () => {
    scrollEntitySelector(1);
});


entitySelector.addEventListener("scroll", () => {
    updateEntitySelectorArrows();
});

/* =========================================================
   ENTITY SELECTOR DRAG SCROLL
   ========================================================= */

let selectorPointerDown = false;
let selectorIsDragging = false;

let selectorDragStartX = 0;
let selectorDragStartScrollLeft = 0;

let selectorSuppressNextClick = false;

const SELECTOR_DRAG_THRESHOLD = 6;


entitySelector.addEventListener("pointerdown", (event) => {

    // Mouse only; touch keeps native horizontal swiping.
    if (
        event.pointerType !== "mouse" ||
        event.button !== 0
    ) {
        return;
    }

    selectorPointerDown = true;
    selectorIsDragging = false;

    // Prevent a stale drag from suppressing a later click.
    selectorSuppressNextClick = false;

    selectorDragStartX = event.clientX;
    selectorDragStartScrollLeft =
        entitySelector.scrollLeft;
});


entitySelector.addEventListener("pointermove", (event) => {

    if (!selectorPointerDown) {
        return;
    }

    const distance =
        event.clientX - selectorDragStartX;

    /*
     * Until the pointer has moved enough, this is still
     * treated as an ordinary click.
     */
    if (
        !selectorIsDragging &&
        Math.abs(distance) <= SELECTOR_DRAG_THRESHOLD
    ) {
        return;
    }

    /*
     * We have now crossed the drag threshold.
     */
    if (!selectorIsDragging) {

        selectorIsDragging = true;
        selectorSuppressNextClick = true;

        entitySelector.classList.add("is-dragging");

        /*
         * Pointer capture begins ONLY after a genuine drag.
         */
        entitySelector.setPointerCapture(
            event.pointerId
        );
    }

    entitySelector.scrollLeft =
        selectorDragStartScrollLeft - distance;

    event.preventDefault();
});


function stopEntitySelectorDragging(event) {

    if (!selectorPointerDown) {
        return;
    }

    selectorPointerDown = false;

    if (selectorIsDragging) {

        selectorIsDragging = false;

        entitySelector.classList.remove(
            "is-dragging"
        );

        if (
            event.pointerId !== undefined &&
            entitySelector.hasPointerCapture(
                event.pointerId
            )
        ) {
            entitySelector.releasePointerCapture(
                event.pointerId
            );
        }
    }

    updateEntitySelectorArrows();
}


entitySelector.addEventListener(
    "pointerup",
    stopEntitySelectorDragging
);


entitySelector.addEventListener(
    "pointercancel",
    (event) => {

        stopEntitySelectorDragging(event);

        // pointercancel is not followed by a normal click.
        selectorSuppressNextClick = false;
    }
);





function renderOverview(entity, metrics) {
    return `
        <header class="entity-overview">

            <h2>${escapeHtml(formatEntityTitle(entity.entity_id))}</h2>

            <p class="entity-interpretation-large">
                ${escapeHtml(
                    entity.interpretation ||
                    (metrics.listingCount === 1
                        ? "Separate dwelling"
                        : "Likely referring to the same dwelling")
                )}
            </p>

            <div class="entity-badges">
                <span class="entity-badge is-primary">
                    ${metrics.listingCount}
                    ${metrics.listingCount === 1 ? "listing" : "listings"}
                </span>

                <span class="entity-badge">
                    ${escapeHtml(humanize(entity.component_type))} component
                </span>

                <span class="entity-badge">
                    Average probability:
                    ${escapeHtml(formatProbability(metrics.averageProbability))}
                </span>

                <span class="entity-badge">
                    Distance from cutoff:
                    ${escapeHtml(
                        formatDistance(metrics.averageProbability, metrics.cutoff)
                    )}
                </span>
            </div>
        </header>
    `;
}

function renderStatistics(entity, metrics) {
    const statistics = [
        [metrics.listingCount, "Listings"],
        [humanize(entity.component_type), "Component type"],
        [formatProbability(metrics.averageProbability), "Average probability"],
        [formatProbability(metrics.minimumProbability), "Lowest pair"],
        [formatProbability(metrics.maximumProbability), "Highest pair"],
    ];

    return `
        <section class="details-statistics" aria-label="Entity statistics">
            ${statistics
                .map(([value, label]) => {
                    return `
                        <div class="details-stat">
                            <strong>${escapeHtml(value)}</strong>
                            <span>${escapeHtml(label)}</span>
                        </div>
                    `;
                })
                .join("")}
        </section>
    `;
}

/* =========================================================
   3D GRAPH
   ========================================================= */

function createGraphData(entity) {
    const internalListings = entity.listings || [];
    const internalIds = new Set(getListingIds(entity));
    const nodeMap = new Map();

    internalListings.forEach((listing) => {
        nodeMap.set(String(listing.ID), {
            id: String(listing.ID),
            listing,
            internal: true,
        });
    });

    (entity.comparisons || []).forEach((comparison) => {
        const first = String(comparison.ID_1 ?? comparison.id_1 ?? "");
        const second = String(comparison.ID_2 ?? comparison.id_2 ?? "");

        [first, second].forEach((id) => {
            if (!id || nodeMap.has(id)) {
                return;
            }

            const external = comparison.external_listing || {};

            nodeMap.set(id, {
                id,
                internal: false,
                listing: {
                    ID: id,
                    Type: external.Type,
                    "Net.Area": external["Net.Area"],
                    Price: external.Price,
                },
            });
        });
    });

    const nodes = [...nodeMap.values()];
    const radius = nodes.length === 1 ? 0 : 125;

    nodes.forEach((node, index) => {
        if (nodes.length === 1) {
            node.position = { x: 0, y: 0, z: 0 };
            return;
        }

        const angle = (index / nodes.length) * Math.PI * 2;

        node.position = {
            x: Math.cos(angle) * radius,
            y: Math.sin(angle) * radius * 0.72,

            // Small depth variation keeps the graph 3D,
            // but makes the initial view mostly planar.
            z: Math.sin(angle * 2) * radius * 0.12,
        };
    });

    const edges = (entity.comparisons || [])
        .map((comparison) => {
            const source = String(comparison.ID_1 ?? comparison.id_1 ?? "");
            const target = String(comparison.ID_2 ?? comparison.id_2 ?? "");

            if (!nodeMap.has(source) || !nodeMap.has(target)) {
                return null;
            }

            return {
                source,
                target,
                probability: getProbability(comparison),
                finalRelation:
                    comparison.final_relation ||
                    (comparison.z_same_group === 1
                        ? "Same entity"
                        : comparison.z_same_group === 0
                            ? "Separated"
                            : ""),
                internal: internalIds.has(source) && internalIds.has(target),
            };
        })
        .filter(Boolean);

    return { nodes, edges };
}

function rotatePoint(point, rotationX, rotationY) {
    const cosY = Math.cos(rotationY);
    const sinY = Math.sin(rotationY);
    const x1 = point.x * cosY - point.z * sinY;
    const z1 = point.x * sinY + point.z * cosY;

    const cosX = Math.cos(rotationX);
    const sinX = Math.sin(rotationX);
    const y2 = point.y * cosX - z1 * sinX;
    const z2 = point.y * sinX + z1 * cosX;

    return { x: x1, y: y2, z: z2 };
}

function projectPoint(point, width, height, zoom) {
    const perspective = 520;
    const scale = (perspective / (perspective + point.z + 220)) * zoom;

    return {
        x: width / 2 + point.x * scale,
        y: height / 2 + point.y * scale,
        scale,
        depth: point.z,
    };
}

const INITIAL_GRAPH_ROTATION_X = 0;
const INITIAL_GRAPH_ROTATION_Y = 0;
const INITIAL_GRAPH_ZOOM = 2;

function initialiseGraph(entity) {
    const stage = document.getElementById("graph-stage");
    const svg = document.getElementById("entity-graph");

    if (!stage || !svg) {
        return;
    }

    graphState = {
        entity,
        stage,
        svg,
        data: createGraphData(entity),

        rotationX: INITIAL_GRAPH_ROTATION_X,
        rotationY: INITIAL_GRAPH_ROTATION_Y,
        zoom: INITIAL_GRAPH_ZOOM,

        dragging: false,
        lastX: 0,
        lastY: 0,
        autoRotate: false,
        showLabels: true,
        showProbabilities: true,
        animationFrame: null,
    };

    stage.addEventListener("pointerdown", onGraphPointerDown);
    window.addEventListener("pointermove", onGraphPointerMove);
    window.addEventListener("pointerup", onGraphPointerUp);
    stage.addEventListener("wheel", onGraphWheel, { passive: false });

    document.getElementById("graph-reset")?.addEventListener("click", resetGraph);
    document.getElementById("graph-auto-rotate")?.addEventListener("click", toggleAutoRotate);
    document.getElementById("graph-labels")?.addEventListener("click", toggleGraphLabels);
    document.getElementById("graph-probabilities")?.addEventListener("click", toggleGraphProbabilities);

    drawGraph();
}

function cleanupGraph() {
    if (!graphState) {
        return;
    }

    cancelAnimationFrame(graphState.animationFrame);
    window.removeEventListener("pointermove", onGraphPointerMove);
    window.removeEventListener("pointerup", onGraphPointerUp);
    graphState = null;
}

function onGraphPointerDown(event) {
    if (!graphState) {
        return;
    }

    graphState.dragging = true;
    graphState.lastX = event.clientX;
    graphState.lastY = event.clientY;
    graphState.stage.setPointerCapture?.(event.pointerId);
}

function onGraphPointerMove(event) {
    if (!graphState?.dragging) {
        return;
    }

    const deltaX = event.clientX - graphState.lastX;
    const deltaY = event.clientY - graphState.lastY;

    graphState.rotationY += deltaX * 0.008;
    graphState.rotationX += deltaY * 0.008;
    graphState.lastX = event.clientX;
    graphState.lastY = event.clientY;

    drawGraph();
}

function onGraphPointerUp() {
    if (graphState) {
        graphState.dragging = false;
    }
}

function onGraphWheel(event) {
    if (!graphState) {
        return;
    }

    event.preventDefault();
    graphState.zoom = Math.min(
        2.2,
        Math.max(0.65, graphState.zoom - event.deltaY * 0.001)
    );

    drawGraph();
}

function resetGraph() {
    if (!graphState) {
        return;
    }

    graphState.rotationX = -0.28;
    graphState.rotationY = 0.48;
    graphState.zoom = 2;
    drawGraph();
}

function toggleAutoRotate(event) {
    if (!graphState) {
        return;
    }

    graphState.autoRotate = !graphState.autoRotate;
    event.currentTarget.classList.toggle("is-active", graphState.autoRotate);

    if (graphState.autoRotate) {
        animateGraph();
    } else {
        cancelAnimationFrame(graphState.animationFrame);
    }
}

function animateGraph() {
    if (!graphState?.autoRotate) {
        return;
    }

    graphState.rotationY += 0.004;
    drawGraph();
    graphState.animationFrame = requestAnimationFrame(animateGraph);
}

function toggleGraphLabels(event) {
    if (!graphState) {
        return;
    }

    graphState.showLabels = !graphState.showLabels;
    event.currentTarget.classList.toggle("is-active", graphState.showLabels);
    drawGraph();
}

function toggleGraphProbabilities(event) {
    if (!graphState) {
        return;
    }

    graphState.showProbabilities = !graphState.showProbabilities;
    event.currentTarget.classList.toggle("is-active", graphState.showProbabilities);
    drawGraph();
}

function drawGraph() {
    if (!graphState) {
        return;
    }

    const { svg, stage, data } = graphState;
    const width = Math.max(stage.clientWidth, 320);
    const height = Math.max(stage.clientHeight, 350);

    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const projectedNodes = new Map();

    data.nodes.forEach((node) => {
        const rotated = rotatePoint(
            node.position,
            graphState.rotationX,
            graphState.rotationY
        );

        projectedNodes.set(
            node.id,
            projectPoint(rotated, width, height, graphState.zoom)
        );
    });

    const edgesMarkup = data.edges
        .map((edge) => {
            const source = projectedNodes.get(edge.source);
            const target = projectedNodes.get(edge.target);

            if (!source || !target) {
                return "";
            }

            const probability = edge.probability ?? 0;
            const rejected = String(edge.finalRelation).toLowerCase().includes("separat");
            const edgeClass = rejected
                ? "is-rejected"
                : probability >= (graphState.entity.cutoff || 0.51)
                    ? "is-positive"
                    : "is-negative";

            const widthValue = Math.max(1.3, 1.2 + probability * 6);
            const midpointX = (source.x + target.x) / 2;
            const midpointY = (source.y + target.y) / 2;

            return `
                <g>
                    <line
                        class="graph-edge ${edgeClass}"
                        x1="${source.x}"
                        y1="${source.y}"
                        x2="${target.x}"
                        y2="${target.y}"
                        stroke-width="${widthValue}"
                        opacity="${edge.internal ? 0.88 : 0.54}"
                    >
                        <title>
                            ${escapeHtml(edge.source)} ↔ ${escapeHtml(edge.target)}
                            | RF2: ${escapeHtml(formatProbability(probability))}
                            | ${escapeHtml(edge.finalRelation || "No final decision")}
                        </title>
                    </line>

                    ${
                        graphState.showProbabilities
                            ? `
                                <text
                                    class="graph-edge-label"
                                    x="${midpointX}"
                                    y="${midpointY - 7}"
                                    text-anchor="middle"
                                >
                                    ${escapeHtml(formatProbability(probability))}
                                </text>
                            `
                            : ""
                    }
                </g>
            `;
        })
        .join("");

    const nodeMarkup = [...data.nodes]
        .sort((a, b) => {
            return projectedNodes.get(a.id).depth - projectedNodes.get(b.id).depth;
        })
        .map((node) => {
            const projected = projectedNodes.get(node.id);
            const radius = Math.max(12, 20 * projected.scale);
            const listing = node.listing || {};

            return `
                <g
                    class="graph-node ${node.internal ? "is-internal" : "is-external"}"
                    data-listing-id="${escapeHtml(node.id)}"
                    transform="translate(${projected.x} ${projected.y})"
                >
                    <circle r="${radius}">
                        <title>
                            ${escapeHtml(node.id)}
                            | ${escapeHtml(listing.Type || "Unknown type")}
                            | ${escapeHtml(
                                listing["Net.Area"] !== undefined
                                    ? `${listing["Net.Area"]} m²`
                                    : "Area unavailable"
                            )}
                            | ${escapeHtml(formatMoney(listing.Price))}
                        </title>
                    </circle>

                    ${
                        graphState.showLabels
                            ? `
                                <text x="0" y="${radius + 19}" text-anchor="middle">
                                    ${escapeHtml(node.id)}
                                </text>
                            `
                            : ""
                    }
                </g>
            `;
        })
        .join("");

    svg.innerHTML = edgesMarkup + nodeMarkup;

    svg.querySelectorAll(".graph-node.is-internal").forEach((node) => {
        node.addEventListener("click", () => {
            const listingId = node.dataset.listingId;
            document.getElementById(`listing-card-${listingId}`)?.scrollIntoView({
                behavior: "smooth",
                block: "start",
            });
        });
    });
}

function renderGraph(entity, metrics) {
    return `
        <section class="graph-layout">
            <article class="panel-card">
                <div class="panel-heading">
                    <div>
                        <h3>Interactive 3D relationship graph</h3>
                        <p>
                            Drag to rotate, scroll to zoom, and click an entity node to open its listing card.
                        </p>
                    </div>

                    <div class="graph-controls" aria-label="Graph controls">
                        <button id="graph-reset" class="graph-control" type="button">Reset view</button>
                        <button id="graph-auto-rotate" class="graph-control" type="button">Auto-rotate</button>
                        <button id="graph-labels" class="graph-control is-active" type="button">Labels</button>
                        <button id="graph-probabilities" class="graph-control is-active" type="button">Probabilities</button>
                    </div>
                </div>

                <div id="graph-stage" class="graph-stage">
                    <svg
                        id="entity-graph"
                        class="entity-graph"
                        role="img"
                        aria-label="Three-dimensional entity relationship graph"
                    ></svg>
                </div>

                <div class="graph-legend" aria-label="Graph legend">
                    <span><i class="legend-dot is-internal"></i>Entity listing</span>
                    <span><i class="legend-dot is-external"></i>External comparison</span>
                    <span><i class="legend-line"></i>Retained relation</span>
                    <span><i class="legend-line is-negative"></i>Below-cutoff relation</span>
                </div>
            </article>

            <aside class="panel-card">
                <div class="panel-heading">
                    <div>
                        <h3>Entity summary</h3>
                        <p>Graph-level evidence for this component.</p>
                    </div>
                </div>

                <dl class="entity-summary-list">
                    <div>
                        <dt>Component type</dt>
                        <dd>${escapeHtml(humanize(entity.component_type))}</dd>
                    </div>
                    <div>
                        <dt>Average probability</dt>
                        <dd>${escapeHtml(formatProbability(metrics.averageProbability))}</dd>
                    </div>
                    <div>
                        <dt>Graph density</dt>
                        <dd>${escapeHtml((metrics.graphDensity * 100).toFixed(1))}%</dd>
                    </div>
                    <div>
                        <dt>Positive internal edges</dt>
                        <dd>${escapeHtml(metrics.positiveEdges)}</dd>
                    </div>
                    <div>
                        <dt>Below-cutoff relations</dt>
                        <dd>${escapeHtml(metrics.negativeEdges)}</dd>
                    </div>
                    <div>
                        <dt>Distinct agencies</dt>
                        <dd>${escapeHtml(metrics.agencyCount)}</dd>
                    </div>
                </dl>
            </aside>
        </section>
    `;
}

/* =========================================================
   ENTITY-LEVEL WEIGHTED INFORMATION
   ========================================================= */

function getEntityWeights(entity) {
    const listings = entity.listings || [];

    // Singleton: the listing itself represents the final entity.
    if (listings.length === 1) {
        return new Map([[String(listings[0].ID), 1]]);
    }

    const listingIds = new Set(listings.map((listing) => String(listing.ID)));
    const internalComparisons = (entity.comparisons || []).filter((comparison) => {
        const first = String(comparison.ID_1 ?? comparison.id_1 ?? "");
        const second = String(comparison.ID_2 ?? comparison.id_2 ?? "");

        return listingIds.has(first) && listingIds.has(second);
    });

    // Calculate each listing's mean internal RF2 probability.
    const confidenceScores = new Map();

    listings.forEach((listing) => {
        const listingId = String(listing.ID);

        const probabilities = internalComparisons
            .filter((comparison) => {
                const first = String(comparison.ID_1 ?? comparison.id_1 ?? "");
                const second = String(comparison.ID_2 ?? comparison.id_2 ?? "");

                return first === listingId || second === listingId;
            })
            .map(getProbability)
            .filter((probability) => probability !== null);

        confidenceScores.set(
            listingId,
            probabilities.length ? average(probabilities) : 0
        );
    });

    // Normalise the confidence scores so that weights sum to 1.
    const totalScore = [...confidenceScores.values()].reduce(
        (sum, score) => sum + score,
        0
    );

    // Fallback to equal weights if no usable RF2 probabilities exist.
    if (totalScore === 0) {
        const equalWeight = 1 / listings.length;

        return new Map(
            listings.map((listing) => [String(listing.ID), equalWeight])
        );
    }

    return new Map(
        [...confidenceScores.entries()].map(([listingId, score]) => [
            listingId,
            score / totalScore,
        ])
    );
}


function weightedNumericValue(listings, weights, getter) {
    let weightedSum = 0;
    let validWeightSum = 0;

    listings.forEach((listing) => {
        const value = Number(getter(listing));
        const weight = weights.get(String(listing.ID)) || 0;

        if (Number.isFinite(value)) {
            weightedSum += value * weight;
            validWeightSum += weight;
        }
    });

    return validWeightSum > 0
        ? weightedSum / validWeightSum
        : null;
}


function getWeightedLocation(listings, weights) {
    const candidates = new Map();

    listings.forEach((listing) => {
        const district = listing.District ?? "";
        const neighborhood = listing.Neighborhood ?? "";
        const street = listing.Street ?? "";

        const key = `${district}|||${neighborhood}|||${street}`;
        const weight = weights.get(String(listing.ID)) || 0;

        if (!candidates.has(key)) {
            candidates.set(key, {
                district,
                neighborhood,
                street,
                weight: 0,
                count: 0,
            });
        }

        const candidate = candidates.get(key);
        candidate.weight += weight;
        candidate.count += 1;
    });

    if (!candidates.size) {
        return {
            district: null,
            neighborhood: null,
            street: null,
        };
    }

    return [...candidates.values()].sort((a, b) => {
        if (b.weight !== a.weight) {
            return b.weight - a.weight;
        }

        return b.count - a.count;
    })[0];
}


function deriveWeightedInformation(entity) {
    const listings = entity.listings || [];

    if (!listings.length) {
        return [];
    }

    const weights = getEntityWeights(entity);

    const weightedPrice = weightedNumericValue(
        listings,
        weights,
        (listing) => listing.Price
    );

    const weightedArea = weightedNumericValue(
        listings,
        weights,
        (listing) => listing["Net.Area"]
    );

    // Following the thesis methodology, Price_m2 is first calculated
    // at listing level and then probability-weighted.
    const weightedPriceM2 = weightedNumericValue(
        listings,
        weights,
        (listing) => {
            const price = Number(listing.Price);
            const area = Number(listing["Net.Area"]);

            return Number.isFinite(price) &&
                Number.isFinite(area) &&
                area > 0
                ? price / area
                : null;
        }
    );

    const location = getWeightedLocation(listings, weights);

    const district =
        location.district !== null &&
        location.district !== undefined &&
        location.district !== ""
            ? String(location.district).startsWith("Praha")
                ? String(location.district)
                : `Praha ${location.district}`
            : "Unavailable";

    return [
        {
            attribute: "Price",
            value:
                weightedPrice !== null
                    ? formatMoney(Math.round(weightedPrice))
                    : "Unavailable",
        },
        {
            attribute: "Net area",
            value:
                weightedArea !== null
                    ? `${weightedArea.toFixed(2)} m²`
                    : "Unavailable",
        },
        {
            attribute: "Price per m²",
            value:
                weightedPriceM2 !== null
                    ? `${formatNumber(Math.round(weightedPriceM2))} CZK/m²`
                    : "Unavailable",
        },
        {
            attribute: "District",
            value: district,
        },
        {
            attribute: "Neighborhood",
            value: location.neighborhood || "Unavailable",
        },
        {
            attribute: "Street",
            value: location.street || "Unavailable",
        },
    ];
}


function renderAgreement(entity) {
    const rows = deriveWeightedInformation(entity);

    return `
        <section class="panel-card agreement-panel">
            <div class="panel-heading">
                <div>
                    <h3>Entity-level Weighted Information</h3>
                    <p>
                        The final entity-level information derived from weighting the final feature scores based on the RF2 pairwise numeric evidence.
                    </p>
                </div>
            </div>

            <div class="evidence-table-wrapper">
                <table class="agreement-table">
                    <thead>
                        <tr>
                            <th scope="col">Attribute</th>
                            <th scope="col">Weighted Value</th>
                        </tr>
                    </thead>

                    <tbody>
                        ${rows
                            .map(
                                (row) => `
                                    <tr>
                                        <td>
                                            <strong>${escapeHtml(row.attribute)}</strong>
                                        </td>
                                        <td>
                                            ${escapeHtml(row.value)}
                                        </td>
                                    </tr>
                                `
                            )
                            .join("")}
                    </tbody>
                </table>
            </div>
        </section>
    `;
}

/* =========================================================
   ENTITY LISTING OVERVIEW
   ========================================================= */

function renderEntityListingOverview(entity) {
    const listings = Array.isArray(entity.listings)
        ? entity.listings
        : [];

    if (!listings.length) {
        return "";
    }

    const rows = listings
        .map((listing) => {

            const district =
                listing.District !== null &&
                listing.District !== undefined &&
                listing.District !== ""
                    ? String(listing.District).startsWith("Praha")
                        ? String(listing.District)
                        : `Praha ${listing.District}`
                    : "Unavailable";

            const area = Number(listing["Net.Area"]);

            return `
                <tr>
                    <td>
                        <strong>
                            ${escapeHtml(
                                listing.ID ?? "Unavailable"
                            )}
                        </strong>
                    </td>

                    <td>
                        ${escapeHtml(
                            listing.Street ?? "Unavailable"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            formatMoney(listing.Price)
                        )}
                    </td>

                    <td>
                        ${
                            Number.isFinite(area)
                                ? `${escapeHtml(formatNumber(area))} m²`
                                : "Unavailable"
                        }
                    </td>

                    <td>
                        ${escapeHtml(
                            listing.Agency ?? "Unavailable"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(district)}
                    </td>

                    <td>
                        ${escapeHtml(
                            listing.Neighborhood ?? "Unavailable"
                        )}
                    </td>
                </tr>
            `;
        })
        .join("");

    return `
        <section class="panel-card entity-listing-overview-panel">

            <div class="panel-heading">
                <div>
                    <h3>Listings Contained in Entity</h3>

                    <p>
                        Overview of the individual advertisements
                        grouped within this resolved dwelling entity.
                    </p>
                </div>
            </div>

            <div class="entity-listing-overview-wrapper">

                <table class="entity-listing-overview-table">

                    <thead>
                        <tr>
                            <th scope="col">ID</th>
                            <th scope="col">Street</th>
                            <th scope="col">Price</th>
                            <th scope="col">Area</th>
                            <th scope="col">Agency</th>
                            <th scope="col">District</th>
                            <th scope="col">Neighbourhood</th>
                        </tr>
                    </thead>

                    <tbody>
                        ${rows}
                    </tbody>

                </table>

            </div>

        </section>
    `;
}

/* =========================================================
   LISTING CARDS
   ========================================================= */

function getAmenities(listing) {
    const amenities = [
        ["Furnished", "Furnished"],
        ["Partly.Furnished", "Partly furnished"],
        ["Wheelchair", "Wheelchair access"],
        ["Elevator", "Elevator"],
        ["Balcony", "Balcony"],
        ["Terrace", "Terrace"],
        ["Loggia", "Loggia"],
        ["Swimming.pool", "Swimming pool"],
        ["Basement", "Basement"],
        ["Parking", "Parking"],
        ["Garage", "Garage"],
    ];

    return amenities
        .filter(([key]) => Number(listing[key]) === 1)
        .map(([, label]) => label);
}

function renderGallery(listing) {
    const images = Array.isArray(listing["Image.URLs"])
        ? [...new Set(listing["Image.URLs"].filter(Boolean))]
        : [];

    if (!images.length) {
        return `
            <div class="gallery-fallback">
                No listing photographs were returned.
            </div>
        `;
    }

    const encodedImages = encodeURIComponent(JSON.stringify(images));

    // Initially show up to six images other than the main image.
    const initialThumbnails = images
        .slice(1, 7)
        .map((imageUrl, index) => {
            const actualIndex = index + 1;

            return `
                <button
                    type="button"
                    data-gallery-thumbnail
                    data-image-index="${actualIndex}"
                    aria-label="Select photograph ${actualIndex + 1}"
                    style="
                        width: 100%;
                        height: 100%;
                        min-width: 0;
                        min-height: 0;
                        padding: 0;
                        border: 0;
                        border-radius: 8px;
                        overflow: hidden;
                        background: #f3f4f6;
                        cursor: pointer;
                    "
                >
                    <img
                        src="${escapeHtml(imageUrl)}"
                        alt="${escapeHtml(
                            `Photograph ${actualIndex + 1} for ${listing.ID}`
                        )}"
                        loading="lazy"
                        style="
                            display: block;
                            width: 100%;
                            height: 100%;
                            object-fit: cover;
                        "
                    >
                </button>
            `;
        })
        .join("");

    return `
        <div
            class="listing-gallery"
            data-gallery
            data-listing-id="${escapeHtml(listing.ID)}"
            data-images="${escapeHtml(encodedImages)}"
            style="
                display: grid;
                grid-template-columns: 400px minmax(0, 1fr);
                grid-template-rows: 400px;
                gap: 12px;

                width: 100%;
                height: 400px;
                min-height: 400px;
                max-height: 400px;

                margin-bottom: 24px;
                overflow: hidden;
            "
        >

            <!-- ==================================================
                 MAIN SELECTED IMAGE
                 ================================================== -->

            <div
                style="
                    position: relative;

                    width: 400px;
                    height: 400px;
                    min-width: 400px;
                    min-height: 400px;

                    overflow: hidden;
                    border-radius: 10px;
                    background: #f3f4f6;
                "
            >
                <button
                    type="button"
                    class="gallery-image-button"
                    data-gallery-main-button
                    data-full-image="${escapeHtml(images[0])}"
                    data-caption="${escapeHtml(`${listing.ID} — image 1`)}"
                    style="
                        display: block;
                        width: 100%;
                        height: 100%;
                        padding: 0;
                        border: 0;
                        background: transparent;
                        cursor: zoom-in;
                    "
                >
                    <img
                        data-gallery-main-image
                        src="${escapeHtml(images[0])}"
                        alt="${escapeHtml(`Photograph 1 for ${listing.ID}`)}"
                        style="
                            display: block;
                            width: 100%;
                            height: 100%;
                            object-fit: cover;
                        "
                    >
                </button>


                ${
                    images.length > 1
                        ? `
                            <!-- Previous image -->

                            <button
                                type="button"
                                data-gallery-previous
                                aria-label="Previous photograph"
                                style="
                                    position: absolute;
                                    top: 50%;
                                    left: 12px;
                                    transform: translateY(-50%);
                                    z-index: 5;

                                    width: 42px;
                                    height: 42px;

                                    border: 0;
                                    border-radius: 50%;

                                    background: rgba(0, 0, 0, 0.58);
                                    color: white;

                                    font-size: 26px;
                                    line-height: 1;

                                    cursor: pointer;
                                "
                            >
                                <span style="
                                    display: block;
                                    line-height: 1;
                                    transform: translate(0px, -4px);
                                ">
                                    &#8249;
                                </span>
                            </button>


                            <!-- Next image -->

                            <button
                                type="button"
                                data-gallery-next
                                aria-label="Next photograph"
                                style="
                                    position: absolute;
                                    top: 50%;
                                    right: 12px;
                                    transform: translateY(-50%);
                                    z-index: 5;

                                    width: 42px;
                                    height: 42px;

                                    border: 0;
                                    border-radius: 50%;

                                    background: rgba(0, 0, 0, 0.58);
                                    color: white;

                                    font-size: 26px;
                                    line-height: 1;

                                    cursor: pointer;
                                "
                            >
                                <span style="
                                    display: block;
                                    line-height: 1;
                                    transform: translate(0px, -4px);
                                ">
                                    &#8250;
                                </span>
                            </button>


                            <!-- Image counter -->

                            <div
                                data-gallery-counter
                                style="
                                    position: absolute;
                                    right: 12px;
                                    bottom: 12px;
                                    z-index: 5;

                                    padding: 5px 10px;
                                    border-radius: 999px;

                                    background: rgba(0, 0, 0, 0.62);
                                    color: white;

                                    font-size: 0.8rem;
                                    font-weight: 600;

                                    pointer-events: none;
                                "
                            >
                                1 / ${images.length}
                            </div>
                        `
                        : ""
                }
            </div>


            <!-- ==================================================
                 2 × 3 THUMBNAIL GRID
                 ================================================== -->

            <div
                data-gallery-thumbnail-grid
                style="
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    grid-template-rows: repeat(2, minmax(0, 1fr));

                    gap: 8px;

                    width: 100%;
                    height: 400px;
                    min-width: 0;
                    min-height: 400px;

                    overflow: hidden;
                "
            >
                ${
                    initialThumbnails ||
                    `
                        <div
                            style="
                                grid-column: 1 / -1;
                                grid-row: 1 / -1;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                color: #6b7280;
                                background: #f3f4f6;
                                border-radius: 8px;
                            "
                        >
                            No additional photographs
                        </div>
                    `
                }
            </div>

        </div>
    `;
}



function renderListingFacts(listing) {
    const facts = [
        ["Price", formatMoney(listing.Price)],
        ["Type", listing.Type],
        [
            "Net area",
            listing["Net.Area"] !== null && listing["Net.Area"] !== undefined
                ? `${listing["Net.Area"]} m²`
                : "Unavailable",
        ],
        ["Floor", listing.Floor],
        [
            "District",
            listing.District !== null && listing.District !== undefined
                ? `Praha ${listing.District}`
                : "Unavailable",
        ],
        ["Street", listing.Street],
        ["Neighborhood", listing.Neighborhood],
        ["Agency", listing.Agency],
        ["Published", listing["Date.Published"]],
        ["Modified", listing["Date.Modified"]],
        [
            "Coordinates",
            Number.isFinite(Number(listing.lat)) && Number.isFinite(Number(listing.lon))
                ? `${Number(listing.lat).toFixed(5)}, ${Number(listing.lon).toFixed(5)}`
                : "Unavailable",
        ],
    ];

    return `
        <dl class="listing-facts">
            ${facts
                .map(([label, value]) => {
                    return `
                        <div class="listing-fact">
                            <dt>${escapeHtml(label)}</dt>
                            <dd>${escapeHtml(value ?? "Unavailable")}</dd>
                        </div>
                    `;
                })
                .join("")}
        </dl>
    `;
}

function getListingComparisons(entity, listingId) {
    return (entity.comparisons || []).filter((comparison) => {
        const first = String(comparison.ID_1 ?? comparison.id_1 ?? "");
        const second = String(comparison.ID_2 ?? comparison.id_2 ?? "");
        return first === String(listingId) || second === String(listingId);
    });
}

function renderListingEvidence(entity, listing) {
    const comparisons = getListingComparisons(entity, listing.ID);
    const probabilities = comparisons
        .map(getProbability)
        .filter((value) => value !== null);

    const meanProbability = average(probabilities);
    const cutoff = Number(entity.cutoff) || 0.51;

    if (!comparisons.length) {
        return `<p>No pairwise comparison was returned for this listing.</p>`;
    }

    return `
        <div class="evidence-table-wrapper">
            <table class="evidence-table">
                <thead>
                    <tr>
                        <th scope="col">Pair</th>
                        <th scope="col">Compared listing</th>
                        <th scope="col">RF2 probability</th>
                        <th scope="col">Distance from .51</th>
                        <th scope="col">RF2 decision</th>
                        <th scope="col">Final relation</th>
                    </tr>
                </thead>
                <tbody>
                    ${comparisons
                        .map((comparison) => {
                            const first = String(comparison.ID_1 ?? comparison.id_1 ?? "");
                            const second = String(comparison.ID_2 ?? comparison.id_2 ?? "");
                            const other = first === String(listing.ID) ? second : first;
                            const probability = getProbability(comparison);
                            const rf2Duplicate = comparison.rf2_match === 1 || comparison.rf2_match === true;
                            const finalRelation =
                                comparison.final_relation ||
                                (comparison.z_same_group === 1
                                    ? "Same entity"
                                    : comparison.z_same_group === 0
                                        ? "Separated"
                                        : "Not adjusted");
                            const finalClass = String(finalRelation).toLowerCase().includes("same")
                                ? "final-same"
                                : "final-separated";

                            return `
                                <tr>
                                    <td>${escapeHtml(first)} – ${escapeHtml(second)}</td>
                                    <td>${escapeHtml(other)}</td>
                                    <td class="probability-value">
                                        ${escapeHtml(formatProbability(probability))}
                                    </td>
                                    <td>${escapeHtml(formatDistance(probability, cutoff))}</td>
                                    <td>${rf2Duplicate ? "Duplicate" : "Non-duplicate"}</td>
                                    <td class="${finalClass}">${escapeHtml(finalRelation)}</td>
                                </tr>
                            `;
                        })
                        .join("")}

                    <tr class="average-row">
                        <td>Average</td>
                        <td></td>
                        <td class="probability-value">
                            ${escapeHtml(formatProbability(meanProbability))}
                        </td>
                        <td></td>
                        <td></td>
                        <td></td>
                    </tr>
                </tbody>
            </table>
        </div>
    `;
}

function renderListingCard(entity, listing) {
    const amenities = getAmenities(listing);
    const sourceUrl = listing["Source.URL"];

    return `
        <article id="listing-card-${escapeHtml(listing.ID)}" class="detail-listing-card">
            <header class="detail-listing-header">
                <div>
                    <h4>Listing ${escapeHtml(listing.ID)}</h4>
                    <p class="listing-headline">
                        ${escapeHtml(listing.Type || "Unknown type")}
                        ·
                        ${escapeHtml(
                            listing["Net.Area"] !== null && listing["Net.Area"] !== undefined
                                ? `${listing["Net.Area"]} m²`
                                : "Area unavailable"
                        )}
                        ·
                        ${escapeHtml(formatMoney(listing.Price))}
                    </p>
                    <p class="listing-location">
                        ${escapeHtml(
                            [listing.Street, listing.Neighborhood]
                                .filter(Boolean)
                                .join(", ") || "Location unavailable"
                        )}
                    </p>
                </div>

                ${
                    sourceUrl
                        ? `
                            <a
                                class="source-link"
                                href="${escapeHtml(sourceUrl)}"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                View original listing <span aria-hidden="true">↗</span>
                            </a>
                        `
                        : ""
                }
            </header>

            ${renderGallery(listing)}

            <section class="listing-subsection">
                <h5>Listing information</h5>
                ${renderListingFacts(listing)}
            </section>

            ${
                amenities.length
                    ? `
                        <section class="listing-subsection">
                            <h5>Amenities</h5>
                            <ul class="amenity-list">
                                ${amenities.map((amenity) => `<li>${escapeHtml(amenity)}</li>`).join("")}
                            </ul>
                        </section>
                    `
                    : ""
            }

            <section class="listing-subsection">
                <h5>Pairwise evidence for ${escapeHtml(listing.ID)}</h5>
                ${renderListingEvidence(entity, listing)}
            </section>
        </article>
    `;
}

function renderListings(entity) {
    return `
        <section>
            <header class="listings-section-header">
                <h3>Listings in this entity</h3>
                <p>
                    Each card preserves the original listing attributes, selected photographs, and listing-specific RF2 evidence.
                </p>
            </header>

            <div class="listing-cards">
                ${(entity.listings || [])
                    .map((listing) => renderListingCard(entity, listing))
                    .join("")}
            </div>
        </section>
    `;
}

/* =========================================================
   TECHNICAL DETAILS
   ========================================================= */

function renderDisclosures(entity) {
    const gerDecisions = (entity.comparisons || []).map((comparison) => ({
        pair: `${comparison.ID_1}--${comparison.ID_2}`,
        rf2_probability: getProbability(comparison),
        rf2_match: comparison.rf2_match,
        final_relation: comparison.final_relation,
        z_same_group: comparison.z_same_group,
    }));

    return `
        <section class="entity-disclosures">
            <details>
                <summary>View entity JSON</summary>
                <pre>${escapeHtml(JSON.stringify(entity, null, 2))}</pre>
            </details>

            <details>
                <summary>View graph memberships</summary>
                <pre>${escapeHtml(JSON.stringify(entity.memberships || [], null, 2))}</pre>
            </details>

            <details>
                <summary>View GER-CC decisions</summary>
                <pre>${escapeHtml(JSON.stringify(gerDecisions, null, 2))}</pre>
            </details>
        </section>
    `;
}

/* =========================================================
   MAIN RENDER
   ========================================================= */

function renderSelectedEntity() {
    cleanupGraph();

    const entity = entities.find(
        (candidate) => candidate.entity_id === selectedEntityId
    );

    if (!entity) {
        entityContent.innerHTML = `
            <div class="panel-card">
                <h2>Entity not found</h2>
                <p>The requested entity is not available.</p>
            </div>
        `;
        return;
    }

    const metrics = getEntityMetrics(entity);

    entityContent.innerHTML = `
        ${renderOverview(entity, metrics)}
        ${renderStatistics(entity, metrics)}
        ${renderGraph(entity, metrics)}
        ${renderAgreement(entity)}
        ${renderEntityListingOverview(entity)}
        ${renderListings(entity)}
        ${renderDisclosures(entity)}
    `;

    initialiseGraph(entity);
    initialiseGalleryButtons();

    const url = new URL(window.location.href);
    url.searchParams.set("entity", entity.entity_id);
    window.history.replaceState({}, "", url);
}

/* =========================================================
   EVENTS
   ========================================================= */

    entitySelector.addEventListener("click", (event) => {

    /*
     * A drag can generate a click when the mouse is
     * released. Ignore exactly that click.
     */
    if (selectorSuppressNextClick) {

        selectorSuppressNextClick = false;

        event.preventDefault();
        event.stopPropagation();

        return;
    }


    /*
     * Normal click: identify the entity card.
     */
    const button = event.target.closest(
        "[data-entity-id]"
    );

    if (!button) {
        return;
    }


    /*
     * Select the requested entity.
     */
    selectedEntityId =
        button.dataset.entityId;


    /*
     * Rebuild selector + entity information.
     */
    renderEntitySelector();
    renderSelectedEntity();


    /*
     * Keep selected card visible in carousel.
     */
    requestAnimationFrame(() => {

        scrollSelectedEntityIntoView();
        updateEntitySelectorArrows();

    });


    /*
     * Bring entity information into view.
     */
    entityContent.scrollIntoView({
        behavior: "smooth",
        block: "start",
    });
});



   

function initialiseGalleryButtons() {

    document.querySelectorAll("[data-gallery]").forEach((gallery) => {

        /* ------------------------------------------------------
           READ IMAGE DATA
           ------------------------------------------------------ */

        let images = [];

        try {
            images = JSON.parse(
                decodeURIComponent(gallery.dataset.images || "")
            );
        } catch (error) {
            console.warn("Could not parse gallery images.", error);
            return;
        }

        if (!images.length) {
            return;
        }


        const listingId = gallery.dataset.listingId || "Listing";

        const mainButton =
            gallery.querySelector("[data-gallery-main-button]");

        const mainImage =
            gallery.querySelector("[data-gallery-main-image]");

        const previousButton =
            gallery.querySelector("[data-gallery-previous]");

        const nextButton =
            gallery.querySelector("[data-gallery-next]");

        const counter =
            gallery.querySelector("[data-gallery-counter]");

        const thumbnailGrid =
            gallery.querySelector("[data-gallery-thumbnail-grid]");


        let currentIndex = 0;


        /* ------------------------------------------------------
           BUILD THUMBNAILS

           Always show the next six photographs other than
           the photograph currently displayed as the main image.
           ------------------------------------------------------ */

        function renderThumbnails() {

            if (!thumbnailGrid) {
                return;
            }

            if (images.length <= 1) {
                thumbnailGrid.innerHTML = `
                    <div
                        style="
                            grid-column: 1 / -1;
                            grid-row: 1 / -1;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            color: #6b7280;
                            background: #f3f4f6;
                            border-radius: 8px;
                        "
                    >
                        No additional photographs
                    </div>
                `;

                return;
            }


            const thumbnailIndices = [];

            /*
             * Start immediately after the current main photograph
             * and continue through the image collection.
             *
             * Wrapping allows the six thumbnails to remain filled
             * even when the main photograph is near the end.
             */

            for (
                let offset = 1;
                offset < images.length &&
                thumbnailIndices.length < 6;
                offset += 1
            ) {
                const index =
                    (currentIndex + offset) % images.length;

                if (index !== currentIndex) {
                    thumbnailIndices.push(index);
                }
            }


            thumbnailGrid.innerHTML = thumbnailIndices
                .map((imageIndex) => {

                    const imageUrl = images[imageIndex];

                    return `
                        <button
                            type="button"
                            data-gallery-thumbnail
                            data-image-index="${imageIndex}"
                            aria-label="Select photograph ${imageIndex + 1}"
                            style="
                                width: 100%;
                                height: 100%;
                                min-width: 0;
                                min-height: 0;

                                padding: 0;
                                border: 0;
                                border-radius: 8px;

                                overflow: hidden;
                                background: #f3f4f6;

                                cursor: pointer;
                            "
                        >
                            <img
                                src="${escapeHtml(imageUrl)}"
                                alt="${escapeHtml(
                                    `Photograph ${imageIndex + 1} for ${listingId}`
                                )}"
                                loading="lazy"
                                style="
                                    display: block;
                                    width: 100%;
                                    height: 100%;
                                    object-fit: cover;
                                "
                            >
                        </button>
                    `;
                })
                .join("");
        }


        /* ------------------------------------------------------
           CHANGE SELECTED IMAGE
           ------------------------------------------------------ */

        function selectImage(index) {

            currentIndex =
                (index + images.length) % images.length;

            const imageUrl = images[currentIndex];

            mainImage.src = imageUrl;

            mainImage.alt =
                `Photograph ${currentIndex + 1} for ${listingId}`;

            mainButton.dataset.fullImage = imageUrl;

            mainButton.dataset.caption =
                `${listingId} — image ${currentIndex + 1}`;

            if (counter) {
                counter.textContent =
                    `${currentIndex + 1} / ${images.length}`;
            }

            renderThumbnails();
        }


        /* ------------------------------------------------------
           PREVIOUS / NEXT ARROWS
           ------------------------------------------------------ */

        previousButton?.addEventListener("click", (event) => {

            event.preventDefault();
            event.stopPropagation();

            selectImage(currentIndex - 1);
        });


        nextButton?.addEventListener("click", (event) => {

            event.preventDefault();
            event.stopPropagation();

            selectImage(currentIndex + 1);
        });


        /* ------------------------------------------------------
           THUMBNAIL SELECTION
           ------------------------------------------------------ */

        thumbnailGrid?.addEventListener("click", (event) => {

            const thumbnail =
                event.target.closest("[data-gallery-thumbnail]");

            if (!thumbnail) {
                return;
            }

            const index =
                Number(thumbnail.dataset.imageIndex);

            if (Number.isInteger(index)) {
                selectImage(index);
            }
        });


        /* ------------------------------------------------------
           MAIN IMAGE -> LIGHTBOX
           ------------------------------------------------------ */

        mainButton?.addEventListener("click", () => {

            lightboxImage.src =
                mainButton.dataset.fullImage;

            lightboxImage.alt =
                mainButton.dataset.caption;

            lightboxCaption.textContent =
                mainButton.dataset.caption;

            lightbox.showModal();
        });


        /* ------------------------------------------------------
           INITIAL STATE
           ------------------------------------------------------ */

        selectImage(0);
    });
}


closeLightboxButton.addEventListener("click", () => {
    lightbox.close();
});

lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) {
        lightbox.close();
    }
});

window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && lightbox.open) {
        lightbox.close();
    }
});

/* =========================================================
   INITIALISE
   ========================================================= */

if (!entities.length) {
    entitySelector.hidden = true;
    entityContent.innerHTML = `
        <div class="panel-card">
            <h2>No entity data available</h2>
            <p>Return to the engine and run an entity-resolution analysis.</p>
        </div>
    `;
} else {
    renderEntitySelector();
    renderSelectedEntity();

    requestAnimationFrame(() => {
        scrollSelectedEntityIntoView();
        updateEntitySelectorArrows();
    });
}

window.addEventListener("resize", () => {
    updateEntitySelectorArrows();
});
