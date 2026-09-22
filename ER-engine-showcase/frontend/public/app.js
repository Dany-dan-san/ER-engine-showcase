"use strict";

/* =========================================================
   CONFIGURATION
   ========================================================= */

const API_BASE_URL =
    window.location.hostname === "127.0.0.1" ||
    window.location.hostname === "localhost"
        ? "http://127.0.0.1:8000"
        : "https://entity-resolution-back-end-git-1061120783596.europe-west1.run.app";
const DEMO_FILE_URL = "media/files/mock_sreality_demo.csv";

/* =========================================================
   DOM ELEMENTS
   ========================================================= */

const form = document.getElementById("engine-form");
const launchButton = document.getElementById("launch-button");

const resultsSection = document.getElementById("results");
const resultsContent = document.getElementById("results-content");

const formMessage = document.getElementById("form-message");

const fileInput = document.getElementById("listing-file");
const fileName = document.getElementById("file-name");

const urlInputs = [
    document.getElementById("listing-url-1"),
    document.getElementById("listing-url-2"),
    document.getElementById("listing-url-3"),
    document.getElementById("listing-url-4"),
];

let loadingTimers = [];

/* =========================================================
   GENERAL HELPERS
   ========================================================= */

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function clearFormMessage() {
    formMessage.textContent = "";
}

function showFormMessage(message) {
    formMessage.textContent = message;
}

function getSubmittedUrls() {
    return urlInputs
        .map((input) => input.value.trim())
        .filter((value) => value !== "");
}

function isValidSrealityUrl(value) {
    try {
        const url = new URL(value);

        const validProtocol = url.protocol === "https:";

        const validHost = [
            "sreality.cz",
            "www.sreality.cz",
        ].includes(url.hostname.toLowerCase());

        const validPath = url.pathname.startsWith("/detail/");

        return validProtocol && validHost && validPath;
    } catch {
        return false;
    }
}

function formatNumber(value) {
    const numericValue = Number(value);

    if (!Number.isFinite(numericValue)) {
        return String(value ?? "");
    }

    return new Intl.NumberFormat("en-US").format(numericValue);
}

function formatProbability(value) {
    const numericValue = Number(value);

    if (!Number.isFinite(numericValue)) {
        return "Unavailable";
    }

    return `${(numericValue * 100).toFixed(1)}%`;
}

function humanizeValue(value) {
    if (value === null || value === undefined || value === "") {
        return "Unavailable";
    }

    return String(value)
        .replaceAll("_", " ")
        .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatEntityTitle(entityId, index) {
    const match = String(entityId || "").match(/(\d+)$/);

    const number = match
        ? match[1].padStart(3, "0")
        : String(index + 1).padStart(3, "0");

    return `Entity ${number}`;
}

/* =========================================================
   SUBMISSION VALIDATION
   ========================================================= */

function validateSubmission(urls, selectedFile) {
    const hasUrls = urls.length > 0;
    const hasFile = Boolean(selectedFile);

    // A user cannot use URLs and a file simultaneously.
    if (hasUrls && hasFile) {
        throw new Error(
            "Use either listing URLs or one uploaded file, not both at the same time."
        );
    }

    // No URLs + no file is valid:
    // the engine will automatically use the demonstration dataset.

    if (hasUrls) {
        if (urls.length < 2 || urls.length > 4) {
            throw new Error("Enter between two and four listing URLs.");
        }

        if (!urls.every(isValidSrealityUrl)) {
            throw new Error(
                "Every URL must be an HTTPS Sreality detail-page URL."
            );
        }

        if (new Set(urls).size !== urls.length) {
            throw new Error(
                "All submitted listing URLs must be different."
            );
        }
    }

    if (hasFile) {
        const extension = selectedFile.name
            .split(".")
            .pop()
            .toLowerCase();

        if (!["csv", "json"].includes(extension)) {
            throw new Error(
                "Only CSV and JSON files are accepted."
            );
        }

        if (selectedFile.size > 2 * 1024 * 1024) {
            throw new Error(
                "The uploaded file cannot exceed 2 MB."
            );
        }
    }
}

/* =========================================================
   LOADING STATE
   ========================================================= */

function clearLoadingTimers() {
    loadingTimers.forEach((timer) => {
        window.clearTimeout(timer);
    });

    loadingTimers = [];
}

function getLoadingSteps(inputMode) {

    if (inputMode === "demo") {
        return [
            "Loading demonstration dataset",
            "Preparing same-street listing pairs",
            "Calculating RF2 pairwise probabilities",
            "Resolving graph relationships",
        ];
    }

    if (inputMode === "file") {
        return [
            "Validating uploaded file",
            "Preparing same-street listing pairs",
            "Calculating RF2 pairwise probabilities",
            "Resolving graph relationships",
        ];
    }

    return [
        "Reading submitted URLs",
        "Extracting and standardising listing data",
        "Calculating RF2 pairwise probabilities",
        "Resolving graph relationships",
    ];
}

function renderLoadingSteps(steps, activeIndex) {
    return steps
        .map((step, index) => {
            let statusClass = "is-pending";
            let icon = "•";

            if (index < activeIndex) {
                statusClass = "is-complete";
                icon = "✓";
            } else if (index === activeIndex) {
                statusClass = "is-active";
            }

            return `
                <li class="progress-item ${statusClass}">
                    <span
                        class="progress-icon"
                        aria-hidden="true"
                    >
                        ${icon}
                    </span>

                    <span>${escapeHtml(step)}</span>
                </li>
            `;
        })
        .join("");
}

function updateLoadingStep(steps, activeIndex) {
    const progressList = document.getElementById(
        "engine-progress-list"
    );

    if (!progressList) {
        return;
    }

    progressList.innerHTML = renderLoadingSteps(
        steps,
        activeIndex
    );
}

function startLoadingState(inputMode) {
    clearLoadingTimers();

    const steps = getLoadingSteps(inputMode);

    launchButton.disabled = true;
    launchButton.textContent = "Analysing listings…";

    resultsSection.hidden = false;
    resultsSection.classList.add("is-loading");
    resultsSection.setAttribute("aria-busy", "true");

    resultsContent.innerHTML = `
        <div class="loading-card">
            <div class="loading-header">
                <span
                    class="loading-spinner"
                    aria-hidden="true"
                ></span>

                <div>
                    <h3>Running entity resolution</h3>

                    <p>
                        Please wait while the submitted listings
                        are processed.
                    </p>
                </div>
            </div>

            <ol
                id="engine-progress-list"
                class="progress-list"
            >
                ${renderLoadingSteps(steps, 0)}
            </ol>
        </div>
    `;

    /*
     * These stages are informative animations.
     * The backend currently returns one final response rather
     * than sending live progress information.
     */
    const stageDelays = [
        700,
        2200,
        4200,
    ];

    stageDelays.forEach((delay, index) => {
        const timer = window.setTimeout(() => {
            updateLoadingStep(
                steps,
                index + 1
            );
        }, delay);

        loadingTimers.push(timer);
    });

    resultsSection.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
    });
}

function stopLoadingState() {
    clearLoadingTimers();

    launchButton.disabled = false;
    launchButton.textContent = "Launch the Engine";

    resultsSection.classList.remove("is-loading");
    resultsSection.removeAttribute("aria-busy");
}

/* =========================================================
   API HELPERS
   ========================================================= */

async function readApiResponse(response) {
    const contentType =
        response.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
        return response.json();
    }

    const responseText = await response.text();

    return {
        detail:
            responseText ||
            "The backend returned an empty response.",
    };
}

function getErrorMessage(data, fallbackMessage) {
    if (!data) {
        return fallbackMessage;
    }

    if (typeof data.detail === "string") {
        return data.detail;
    }

    if (Array.isArray(data.detail)) {
        return data.detail
            .map((item) => {
                if (typeof item === "string") {
                    return item;
                }

                return item.msg || JSON.stringify(item);
            })
            .join(" ");
    }

    if (typeof data.message === "string") {
        return data.message;
    }

    return fallbackMessage;
}

/* =========================================================
   API REQUEST: URL COMPARISON
   ========================================================= */

async function submitUrls(urls) {
    const response = await fetch(
        `${API_BASE_URL}/api/compare-urls`,
        {
            method: "POST",

            headers: {
                "Content-Type": "application/json",
            },

            body: JSON.stringify({
                listing_urls: urls,
            }),
        }
    );

    const data = await readApiResponse(response);

    if (!response.ok) {
        throw new Error(
            getErrorMessage(
                data,
                "The URL comparison could not be completed."
            )
        );
    }

    return data;
}

/* =========================================================
   API REQUEST: FILE ANALYSIS
   ========================================================= */

   async function loadDemoFile() {
    const response = await fetch(DEMO_FILE_URL);

    if (!response.ok) {
        throw new Error(
            "The demonstration dataset could not be loaded."
        );
    }

    const blob = await response.blob();

    return new File(
        [blob],
        "mock_sreality_demo.csv",
        {
            type: "text/csv",
        }
    );
}

async function submitFile(selectedFile) {
    const formData = new FormData();

    /*
     * The field name "file" must match the UploadFile
     * parameter expected by the FastAPI route.
     */
    formData.append("file", selectedFile);

    const response = await fetch(
        `${API_BASE_URL}/api/analyse-file`,
        {
            method: "POST",
            body: formData,
        }
    );

    const data = await readApiResponse(response);

    if (!response.ok) {
        throw new Error(
            getErrorMessage(
                data,
                "The uploaded file could not be analysed."
            )
        );
    }

    return data;
}

/* =========================================================
   RESULT HELPERS
   ========================================================= */

function getResultObject(data) {
    if (
        data &&
        typeof data.result === "object" &&
        data.result !== null
    ) {
        return data.result;
    }

    return data || {};
}

function getEntities(result) {
    if (Array.isArray(result.entities)) {
        return result.entities;
    }

    if (
        result.graph_resolution &&
        Array.isArray(result.graph_resolution.entities)
    ) {
        return result.graph_resolution.entities;
    }

    return [];
}

function getComparisons(result) {
    if (Array.isArray(result.comparisons)) {
        return result.comparisons;
    }

    return [];
}

function getGraphResolution(result) {
    if (
        result.graph_resolution &&
        typeof result.graph_resolution === "object"
    ) {
        return result.graph_resolution;
    }

    return null;
}

function getListingLabel(listing) {
    const parts = [];

    if (listing.Street) {
        parts.push(listing.Street);
    }

    if (listing.Type) {
        parts.push(listing.Type);
    }

    if (listing["Net.Area"] !== null &&
        listing["Net.Area"] !== undefined) {
        parts.push(`${listing["Net.Area"]} m²`);
    }

    if (listing.Price !== null &&
        listing.Price !== undefined) {
        parts.push(`${formatNumber(listing.Price)} CZK`);
    }

    if (parts.length === 0) {
        return listing.ID || "Listing";
    }

    return parts.join(" · ");
}

/* =========================================================
   ENTITY CARDS
   ========================================================= */

function renderEntityListings(entity) {
    if (
        Array.isArray(entity.listings) &&
        entity.listings.length > 0
    ) {
        return entity.listings
            .map((listing) => {
                const listingId =
                    listing.ID ||
                    listing.id ||
                    "Unknown ID";

                return `
                    <li>
                        <strong>
                            ${escapeHtml(listingId)}
                        </strong>

                        <span>
                            ${escapeHtml(
                                getListingLabel(listing)
                            )}
                        </span>
                    </li>
                `;
            })
            .join("");
    }

    if (
        Array.isArray(entity.listing_ids) &&
        entity.listing_ids.length > 0
    ) {
        return entity.listing_ids
            .map((listingId) => {
                return `
                    <li>
                        <strong>
                            ${escapeHtml(listingId)}
                        </strong>
                    </li>
                `;
            })
            .join("");
    }

    return `
        <li>
            Listing information unavailable
        </li>
    `;
}

function getComparisonProbability(comparison) {
    const value =
        comparison.rf2_probability ??
        comparison.prob_duplicate_rf2;

    const probability = Number(value);

    return Number.isFinite(probability)
        ? probability
        : null;
}

function getEntityDuplicateProbability(
    entity,
    comparisons
) {
    const listingIds = new Set(
        Array.isArray(entity.listing_ids)
            ? entity.listing_ids.map(String)
            : (
                Array.isArray(entity.listings)
                    ? entity.listings
                        .map((listing) => listing.ID)
                        .filter(Boolean)
                        .map(String)
                    : []
            )
    );

    if (listingIds.size === 0) {
        return null;
    }

    /*
     * For a multi-listing entity, calculate the arithmetic
     * average of all RF2 probabilities between listings
     * assigned to that same final entity.
     */
    if (listingIds.size > 1) {
        const internalProbabilities = comparisons
            .filter((comparison) => {
                const firstId = String(
                    comparison.ID_1 ??
                    comparison.id_1 ??
                    ""
                );

                const secondId = String(
                    comparison.ID_2 ??
                    comparison.id_2 ??
                    ""
                );

                return (
                    listingIds.has(firstId) &&
                    listingIds.has(secondId)
                );
            })
            .map(getComparisonProbability)
            .filter((probability) => probability !== null);

        if (internalProbabilities.length === 0) {
            return null;
        }

        const total = internalProbabilities.reduce(
            (sum, probability) => sum + probability,
            0
        );

        return total / internalProbabilities.length;
    }

    /*
     * For a singleton, calculate the arithmetic average of
     * every RF2 probability involving that listing.
     */
    const singletonId = [...listingIds][0];

    const relatedProbabilities = comparisons
        .filter((comparison) => {
            const firstId = String(
                comparison.ID_1 ??
                comparison.id_1 ??
                ""
            );

            const secondId = String(
                comparison.ID_2 ??
                comparison.id_2 ??
                ""
            );

            return (
                firstId === singletonId ||
                secondId === singletonId
            );
        })
        .map(getComparisonProbability)
        .filter((probability) => probability !== null);

    if (relatedProbabilities.length === 0) {
        return null;
    }

    const total = relatedProbabilities.reduce(
        (sum, probability) => sum + probability,
        0
    );

    return total / relatedProbabilities.length;
}

function formatProbabilityPercent(probability) {
    if (!Number.isFinite(probability)) {
        return "Unavailable";
    }

    return `${(probability * 100).toFixed(2)}%`;
}

function formatCutoffDistance(
    probability,
    cutoff
) {
    if (
        !Number.isFinite(probability) ||
        !Number.isFinite(cutoff)
    ) {
        return "Unavailable";
    }

    const distance = Math.abs(
        probability - cutoff
    );

    return `${(distance * 100).toFixed(2)}`;
}

function renderEntityCard(
    entity,
    index,
    comparisons,
    cutoff
) {
    const entityId =
        entity.entity_id ||
        `ENTITY_${String(index + 1).padStart(3, "0")}`;

    const listingIds = Array.isArray(entity.listing_ids)
        ? entity.listing_ids
        : [];

    const listingCount =
        entity.group_size ??
        entity.entity_size ??
        entity.listings?.length ??
        listingIds.length ??
        0;

    const numericListingCount = Number(listingCount);

    const componentType =
        entity.component_type ||
        "unavailable";

    const isSingleton =
        entity.is_singleton === true ||
        numericListingCount === 1;

    const interpretation = isSingleton
        ? "Separate dwelling"
        : "Likely referring to the same dwelling";

    const duplicateProbability =
        getEntityDuplicateProbability(
            entity,
            comparisons
        );

    const formattedProbability =
        formatProbabilityPercent(
            duplicateProbability
        );

    const cutoffDistance =
        formatCutoffDistance(
            duplicateProbability,
            cutoff
        );

    return `
        <article class="entity-card">
            <header class="entity-card-header">
                <h3 class="entity-title">
                    ${escapeHtml(
                        formatEntityTitle(entityId, index)
                    )}
                </h3>

                <p class="entity-interpretation">
                    ${escapeHtml(interpretation)}
                </p>

                <p class="entity-listing-count">
                    <strong>
                        ${formatNumber(listingCount)}
                        ${
                            numericListingCount === 1
                                ? "listing"
                                : "listings"
                        }
                    </strong>
                </p>
            </header>

            <ul class="entity-listings">
                ${renderEntityListings(entity)}
            </ul>

            <div class="entity-component">
                <div class="entity-component-row">
                    <p>
                        <strong>Component type:</strong>
                        ${escapeHtml(
                            humanizeValue(componentType)
                        )}
                    </p>

                    <p>
                        <strong>Duplicate Prob.:</strong>
                        <span class="entity-probability">
                            ${escapeHtml(formattedProbability)}
                        </span>
                    </p>
                </div>

                <p class="entity-cutoff-distance">
                    <strong>
                        Distance from cutoff (.51):
                    </strong>

                    <span>
                        ${escapeHtml(cutoffDistance)}
                    </span>
                </p>
            </div>
        </article>
    `;
}

/* =========================================================
   PAIRWISE EVIDENCE
   ========================================================= */

function renderComparisonRows(comparisons) {
    return comparisons
        .map((comparison) => {
            const firstId =
                comparison.ID_1 ||
                comparison.id_1 ||
                "Listing 1";

            const secondId =
                comparison.ID_2 ||
                comparison.id_2 ||
                "Listing 2";

            const probability =
                comparison.rf2_probability ??
                comparison.prob_duplicate_rf2;

            const initialMatch =
                comparison.rf2_match ??
                comparison.match;

            const finalDecision =
                comparison.z_same_group;

            let initialLabel = "Unavailable";

            if (initialMatch === 1 || initialMatch === true) {
                initialLabel = "Duplicate";
            } else if (
                initialMatch === 0 ||
                initialMatch === false
            ) {
                initialLabel = "Non-duplicate";
            }

            let finalLabel = "Not adjusted";

            if (finalDecision === 1) {
                finalLabel = "Together";
            } else if (finalDecision === 0) {
                finalLabel = "Separated";
            }

            return `
                <tr>
                    <td>
                        ${escapeHtml(firstId)}
                        –
                        ${escapeHtml(secondId)}
                    </td>

                    <td>
                        ${escapeHtml(
                            formatProbability(probability)
                        )}
                    </td>

                    <td>
                        ${escapeHtml(initialLabel)}
                    </td>

                    <td>
                        ${escapeHtml(finalLabel)}
                    </td>
                </tr>
            `;
        })
        .join("");
}

function renderPairwiseEvidence(comparisons) {
    if (comparisons.length === 0) {
        return "";
    }

    return `
        <details class="result-details">
            <summary>
                View pairwise evidence
            </summary>

            <div class="table-wrapper">
                <table class="comparison-table">
                    <thead>
                        <tr>
                            <th scope="col">Listing pair</th>
                            <th scope="col">RF2 probability</th>
                            <th scope="col">Initial decision</th>
                            <th scope="col">Final grouping</th>
                        </tr>
                    </thead>

                    <tbody>
                        ${renderComparisonRows(comparisons)}
                    </tbody>
                </table>
            </div>
        </details>
    `;
}

/* =========================================================
   GRAPH SUMMARY
   ========================================================= */

function renderResultStatistics({
    inputCount,
    comparablePairCount,
    entityCount,
    graphResolution,
}) {
    const completeComponents =
        graphResolution?.complete_component_count ?? 0;

    const problematicComponents =
        graphResolution
            ?.incomplete_problematic_component_count ?? 0;

    const duplicateEntities =
        graphResolution?.duplicate_entity_count ?? 0;

    const singletonEntities =
        graphResolution?.singleton_entity_count ?? 0;

    const statistics = [
        {
            value: inputCount,
            label: "Submitted listings",
        },
        {
            value: comparablePairCount,
            label: "Comparable pairs",
        },
        {
            value: entityCount,
            label: "Final entities",
        },
        {
            value: completeComponents,
            label: "Complete components",
        },
        {
            value: problematicComponents,
            label: "Problematic components",
        },
        {
            value: duplicateEntities,
            label: "Duplicate groups",
        },
        {
            value: singletonEntities,
            label: "Singletons",
        },
    ];

    return `
        <div class="result-statistics">
            ${statistics
                .map((statistic) => {
                    return `
                        <div class="result-stat">
                            <strong>
                                ${formatNumber(statistic.value)}
                            </strong>

                            <span>
                                ${escapeHtml(statistic.label)}
                            </span>
                        </div>
                    `;
                })
                .join("")}
        </div>
    `;
}

/* =========================================================
   SUCCESS RESULT
   ========================================================= */

function renderSuccess(data) {
    const result = data.result || data;

    if (!Array.isArray(result.entities)) {
        throw new Error(
            "The backend response did not contain resolved entities."
        );
    }

    /*
     * Save the information required by entity_details.js.
     *
     * sessionStorage survives navigation between pages in
     * the same browser tab.
     */
    sessionStorage.setItem(
        "erEntityDetails",
        JSON.stringify({
            entities: result.entities,
            comparisons: Array.isArray(result.comparisons)
                ? result.comparisons
                : [],
        })
    );

    /*
     * Open the entity-details interface.
     */
    window.location.href = "entity_details.html";
}

/* =========================================================
   NO COMPARABLE PAIRS RESULT
   ========================================================= */

function renderNoComparablePairs(data, result) {
    const inputCount =
        data.input_count ??
        result.input_listing_count ??
        result.input_count ??
        0;

    const message =
        result.message ||
        "None of the submitted listings shared the same normalized street. No RF2 predictions were calculated.";

    resultsContent.innerHTML = `
        <div class="result-header">
            <p class="result-status">
                Analysis complete
            </p>

            <h3>No comparable listing pairs</h3>

            <p>${escapeHtml(message)}</p>
        </div>

        <div class="result-statistics">
            <div class="result-stat">
                <strong>
                    ${formatNumber(inputCount)}
                </strong>

                <span>Submitted listings</span>
            </div>

            <div class="result-stat">
                <strong>0</strong>
                <span>Comparable pairs</span>
            </div>
        </div>

        <details class="result-details">
            <summary>
                View technical response
            </summary>

            <pre>${escapeHtml(
                JSON.stringify(data, null, 2)
            )}</pre>
        </details>
    `;

    resultsSection.scrollIntoView({
        behavior: "smooth",
        block: "start",
    });
}

/* =========================================================
   ERROR RESULT
   ========================================================= */

function renderError(error) {
    resultsSection.hidden = false;

    const message =
        error instanceof Error
            ? error.message
            : "An unexpected error occurred.";

    resultsContent.innerHTML = `
        <div class="result-error">
            <p class="result-status">
                Analysis failed
            </p>

            <h3>
                The analysis could not be completed
            </h3>

            <p>
                ${escapeHtml(message)}
            </p>

            <p>
                Confirm that the Docker backend is running and
                that the submitted URLs or file are valid.
            </p>
        </div>
    `;

    resultsSection.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
    });
}

/* =========================================================
   FILE INPUT EVENT
   ========================================================= */

fileInput.addEventListener("change", () => {
    const selectedFile = fileInput.files[0];

    fileName.textContent = selectedFile
        ? selectedFile.name
        : "No file selected";

    clearFormMessage();
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    clearFormMessage();

    const urls = getSubmittedUrls();
    const selectedFile = fileInput.files[0];

    try {
        validateSubmission(urls, selectedFile);
    } catch (error) {
        showFormMessage(error.message);
        return;
    }


    /* =====================================================
       DETERMINE INPUT MODE
       ===================================================== */

    let inputMode;

    if (selectedFile) {
        inputMode = "file";
    } else if (urls.length > 0) {
        inputMode = "urls";
    } else {
        inputMode = "demo";
    }


    /* =====================================================
       RUN ENGINE
       ===================================================== */

    try {
        startLoadingState(inputMode);

        let data;

        if (inputMode === "file") {

            data = await submitFile(selectedFile);

        } else if (inputMode === "urls") {

            data = await submitUrls(urls);

        } else {

            const demoFile = await loadDemoFile();

            data = await submitFile(demoFile);

        }

        stopLoadingState();

        renderSuccess(data);

    } catch (error) {

        stopLoadingState();
        renderError(error);

    }
});

/* =========================================================
   URL INPUT EVENTS
   ========================================================= */

urlInputs.forEach((input) => {
    input.addEventListener("input", () => {
        clearFormMessage();
    });
});

/* =========================================================
   MULTI-URL PASTE
   ========================================================= */

urlInputs[0].addEventListener("paste", (event) => {

    const pastedText = event.clipboardData
        ?.getData("text")
        ?.trim();

    if (!pastedText) {
        return;
    }

    /*
     * Split pasted content on commas or line breaks.
     *
     * Example:
     * url1, url2, url3, url4
     */
    const pastedUrls = pastedText
        .split(/[,\r\n]+/)
        .map((url) => url.trim())
        .filter(Boolean)
        .filter(isValidSrealityUrl);

    /*
     * A normal single-URL paste should behave normally.
     */
    if (pastedUrls.length < 2) {
        return;
    }

    /*
     * We are handling the paste ourselves.
     */
    event.preventDefault();

    /*
     * Populate at most the four available URL inputs.
     */
    pastedUrls
        .slice(0, urlInputs.length)
        .forEach((url, index) => {
            urlInputs[index].value = url;
        });

    /*
     * If fewer than four URLs were pasted, clear any
     * leftover values from subsequent fields.
     */
    for (
        let index = pastedUrls.length;
        index < urlInputs.length;
        index += 1
    ) {
        urlInputs[index].value = "";
    }

    clearFormMessage();
});

/* =========================================================
   FORM SUBMISSION
   ========================================================= */

function getLoadingSteps(inputMode) {

    if (inputMode === "demo") {
        return [
            "Loading demonstration dataset",
            "Preparing same-street listing pairs",
            "Calculating RF2 pairwise probabilities",
            "Resolving graph relationships",
        ];
    }

    if (inputMode === "file") {
        return [
            "Validating uploaded file",
            "Preparing same-street listing pairs",
            "Calculating RF2 pairwise probabilities",
            "Resolving graph relationships",
        ];
    }

    return [
        "Reading submitted URLs",
        "Extracting and standardising listing data",
        "Calculating RF2 pairwise probabilities",
        "Resolving graph relationships",
    ];
}
