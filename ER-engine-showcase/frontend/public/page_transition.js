"use strict";


/* =========================================================
   PANEL TRANSITION
   ========================================================= */

const panel = document.querySelector(".engine-panel");


/* =========================================================
   PAGE ENTER
   ========================================================= */

if (panel) {
    panel.classList.add("panel-enter");

    panel.addEventListener(
        "animationend",
        () => {
            panel.classList.remove("panel-enter");
        },
        { once: true }
    );
}


/* =========================================================
   PAGE EXIT
   ========================================================= */

document.querySelectorAll(".main-menu-link").forEach((link) => {

    link.addEventListener("click", (event) => {

        const href = link.getAttribute("href");

        if (
            !href ||
            link.classList.contains("is-active")
        ) {
            return;
        }

        event.preventDefault();

        if (!panel) {
            window.location.href = href;
            return;
        }

        panel.classList.remove("panel-enter");
        panel.classList.add("panel-leaving");

        setTimeout(() => {
            window.location.href = href;
        }, 220);

    });

});


/* =========================================================
   BACK / FORWARD CACHE RESET
   ========================================================= */

window.addEventListener("pageshow", () => {

    if (!panel) {
        return;
    }

    panel.classList.remove("panel-leaving");

});
