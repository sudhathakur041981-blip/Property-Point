const commercialSearch = document.getElementById("commercialSearch");
const commercialEmpty = document.getElementById("commercialEmpty");
const commercialCount = document.getElementById("commercialCount");
const commercialFilters = document.querySelectorAll(".commercial-filter");
let activeCommercialFilter = "all";

function filterCommercialProperties() {
    const query = commercialSearch.value.trim().toLowerCase();
    const commercialCards = document.querySelectorAll(".commercial-card");
    let visibleCount = 0;

    commercialCards.forEach(card => {
        const matchesPurpose =
            activeCommercialFilter === "all" ||
            card.dataset.purpose === activeCommercialFilter;
        const matchesSearch = card.dataset.search.includes(query);
        const isVisible = matchesPurpose && matchesSearch;

        card.hidden = !isVisible;
        if (isVisible) {
            visibleCount++;
        }
    });

    commercialEmpty.classList.toggle("visible", visibleCount === 0);
    commercialCount.textContent =
        `${visibleCount} ${visibleCount === 1 ? "property" : "properties"}`;
}

commercialFilters.forEach(button => {
    button.addEventListener("click", () => {
        activeCommercialFilter = button.dataset.filter;
        commercialFilters.forEach(filterButton => {
            const isActive = filterButton === button;
            filterButton.classList.toggle("active", isActive);
            filterButton.setAttribute("aria-pressed", String(isActive));
        });
        filterCommercialProperties();
    });
});

commercialSearch.addEventListener("input", filterCommercialProperties);
