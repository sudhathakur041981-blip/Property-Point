const landSearch = document.getElementById("landSearch");
const landEmpty = document.getElementById("landEmpty");
const landCount = document.getElementById("landCount");
const landFilters = document.querySelectorAll(".land-filter");
let activeLandFilter = "all";

function filterLandProperties() {
    const query = landSearch.value.trim().toLowerCase();
    const landCards = document.querySelectorAll(".land-card");
    let visibleCount = 0;

    landCards.forEach(card => {
        const matchesPurpose =
            activeLandFilter === "all" ||
            card.dataset.purpose === activeLandFilter;
        const matchesSearch = card.dataset.search.includes(query);
        const isVisible = matchesPurpose && matchesSearch;

        card.hidden = !isVisible;
        if (isVisible) {
            visibleCount++;
        }
    });

    landEmpty.classList.toggle("visible", visibleCount === 0);
    landCount.textContent =
        `${visibleCount} ${visibleCount === 1 ? "listing" : "listings"}`;
}

landFilters.forEach(button => {
    button.addEventListener("click", () => {
        activeLandFilter = button.dataset.filter;
        landFilters.forEach(filterButton => {
            const isActive = filterButton === button;
            filterButton.classList.toggle("active", isActive);
            filterButton.setAttribute("aria-pressed", String(isActive));
        });
        filterLandProperties();
    });
});

landSearch.addEventListener("input", filterLandProperties);
