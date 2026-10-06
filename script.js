// ==============================
// MOBILE MENU
// ==============================

function toggleMenu() {
    const nav = document.querySelector(".navbar nav");
    if (!nav) return;

    if (nav.style.display === "flex") {
        nav.style.display = "none";
    } else {
        nav.style.display = "flex";
        nav.style.flexDirection = "column";
        nav.style.position = "absolute";
        nav.style.top = "78px";
        nav.style.left = "0";
        nav.style.right = "0";
        nav.style.background = "white";
        nav.style.padding = "25px";
        nav.style.boxShadow = "0 8px 20px rgba(0,0,0,0.1)";
    }
}


// ==============================
// PERSISTENT FAVORITES (LOCALSTORAGE)
// ==============================

function getStoredFavorites() {
    try {
        return JSON.parse(localStorage.getItem("pp_favorites") || "[]");
    } catch {
        return [];
    }
}

function toggleStoredFavorite(id) {
    if (!id) return false;
    let favs = getStoredFavorites();
    const index = favs.indexOf(id);
    let isAdded = false;
    if (index > -1) {
        favs.splice(index, 1);
    } else {
        favs.push(id);
        isAdded = true;
    }
    localStorage.setItem("pp_favorites", JSON.stringify(favs));
    updateNavFavCount();
    return isAdded;
}

function updateNavFavCount() {
    const countEl = document.getElementById("navFavCount");
    if (countEl) {
        const count = getStoredFavorites().length;
        countEl.textContent = count;
        countEl.style.display = count > 0 ? "flex" : "none";
    }
}

function favoriteProperty(button, id) {
    const card = button.closest(".property-card");
    const propertyId = id || card?.dataset?.id || card?.dataset?.location + card?.querySelector("h3")?.textContent;

    const isNowFav = toggleStoredFavorite(propertyId);
    button.classList.toggle("active", isNowFav);

    const icon = button.querySelector("i");
    if (icon) {
        icon.classList.toggle("fa-solid", isNowFav);
        icon.classList.toggle("fa-regular", !isNowFav);
        icon.style.color = isNowFav ? "#e63946" : "";
    }
}

async function openFavoritesModal() {
    const modal = document.getElementById("favoritesModal");
    if (!modal) return;
    modal.classList.add("show");
    await renderFavoritesModalList();
}

function closeFavoritesModal() {
    const modal = document.getElementById("favoritesModal");
    if (modal) modal.classList.remove("show");
}

async function renderFavoritesModalList() {
    const container = document.getElementById("favoritesListGrid");
    const emptyMsg = document.getElementById("emptyFavoritesMsg");
    if (!container) return;

    const favIds = getStoredFavorites();
    if (favIds.length === 0) {
        container.innerHTML = "";
        if (emptyMsg) emptyMsg.style.display = "block";
        return;
    }
    if (emptyMsg) emptyMsg.style.display = "none";
    container.innerHTML = "<p>Loading saved homes...</p>";

    try {
        const res = await requestApi("/api/properties?limit=100");
        const matched = res.items.filter(item => favIds.includes(item.id));

        if (matched.length === 0) {
            container.innerHTML = "<p>Your saved properties are no longer active.</p>";
            return;
        }

        container.innerHTML = "";
        matched.forEach(item => {
            const row = document.createElement("div");
            row.className = "favorite-item-card";
            const fallback = "https://images.unsplash.com/photo-1600607687920-4e2a09cf159d?auto=format&fit=crop&w=300&q=80";
            row.innerHTML = `
                <img src="${item.imageUrl || fallback}" alt="${item.title}">
                <div class="fav-item-info">
                    <h4><a href="property.html?id=${item.id}">${item.title}</a></h4>
                    <p><i class="fa-solid fa-location-dot"></i> ${item.location} &bull; ${item.propertyType}</p>
                </div>
                <strong class="fav-item-price">${formatPropertyPrice(item.expectedPrice)}${item.purpose.toLowerCase() === 'rent' ? '/mo' : ''}</strong>
                <button class="fav-remove-btn" title="Remove" onclick="removeFavoriteItem('${item.id}')">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            `;
            container.appendChild(row);
        });
    } catch {
        container.innerHTML = "<p>Could not load saved homes list.</p>";
    }
}

function removeFavoriteItem(id) {
    toggleStoredFavorite(id);
    renderFavoritesModalList();
    // Update any buttons on the page
    document.querySelectorAll(`.property-card[data-id="${id}"] .favorite`).forEach(btn => {
        btn.classList.remove("active");
        const icon = btn.querySelector("i");
        if (icon) {
            icon.className = "fa-regular fa-heart";
            icon.style.color = "";
        }
    });
}


// ==============================
// PROPERTY SEARCH & CLIENT FILTER
// ==============================

function searchProperties(scrollToResults = true) {
    const purposeEl = document.getElementById("purpose");
    if (!purposeEl) return;

    const purpose = purposeEl.value;
    const selectedTypes = Array.from(
        document.querySelectorAll('input[name="propertyType"]:checked')
    ).map(checkbox => checkbox.value);

    const location = (document.getElementById("location")?.value || "").toLowerCase().trim();
    const cards = document.querySelectorAll("#propertyGrid .property-card");
    const budget = document.getElementById("budgetFilter")?.value || "any";
    const bedrooms = document.getElementById("bedroomFilter")?.value || "any";
    const area = document.getElementById("areaFilter")?.value || "any";

    let found = 0;

    cards.forEach(card => {
        const cardPurpose = card.dataset.purpose;
        const cardType = card.dataset.type;
        const cardLocation = card.dataset.location || "";

        const purposeMatch = purpose === "all" || cardPurpose === purpose;
        const typeMatch = selectedTypes.length === 0 || selectedTypes.includes(cardType);
        const locationMatch = location === "" || cardLocation.includes(location);

        const priceEl = card.querySelector(".property-bottom strong");
        const priceText = priceEl ? priceEl.textContent : "0";
        const price = parsePropertyPrice(priceText);
        const budgetMatch = matchesBudget(price, budget, cardPurpose);

        const detailsText = card.querySelector(".property-details")?.textContent || "";
        const bedroomMatchCount = detailsText.match(/(\d+)\s+Beds?/i);
        const bedroomCount = bedroomMatchCount ? Number(bedroomMatchCount[1]) : 0;
        const bedroomMatch =
            bedrooms === "any" ||
            (bedrooms === "5" ? bedroomCount >= 5 : bedroomCount === Number(bedrooms));

        const areaMatchValue = detailsText.match(/([\d,]+)\s*sq\.?\s*ft/i);
        const areaSize = areaMatchValue ? Number(areaMatchValue[1].replace(/,/g, "")) : 0;
        const areaMatch = matchesArea(areaSize, area);

        if (purposeMatch && typeMatch && locationMatch && budgetMatch && bedroomMatch && areaMatch) {
            card.style.display = "block";
            found++;
        } else {
            card.style.display = "none";
        }
    });

    const noResults = document.getElementById("noResults");
    if (noResults) {
        noResults.style.display = found === 0 ? "block" : "none";
    }

    if (scrollToResults && document.getElementById("properties")) {
        document.getElementById("properties").scrollIntoView({ behavior: "smooth" });
    }
}

function parsePropertyPrice(priceText) {
    const amount = Number(priceText.replace(/[^\d.]/g, ""));
    if (priceText.includes("Cr")) return amount * 10000000;
    if (priceText.includes("Lakh")) return amount * 100000;
    return amount;
}

function matchesBudget(price, budget, purpose) {
    if (budget === "any") return true;

    const ranges = purpose === "rent"
        ? {
            under: [0, 25000],
            middle: [25000, 50000],
            upper: [50000, 100000],
            over: [100000, Infinity]
        }
        : {
            under: [0, 5000000],
            middle: [5000000, 10000000],
            upper: [10000000, 20000000],
            over: [20000000, Infinity]
        };

    const range = ranges[budget];
    if (!range) return true;
    const [minimum, maximum] = range;
    return price >= minimum && price < maximum;
}

function matchesArea(area, range) {
    if (range === "any") return true;
    if (range === "under-1000") return area < 1000;
    if (range === "over-2000") return area > 2000;
    const [minimum, maximum] = range.split("-").map(Number);
    return area >= minimum && area <= maximum;
}

function showAllProperties() {
    document.querySelectorAll("#propertyGrid .property-card").forEach(card => {
        card.style.display = "block";
    });
    const noResults = document.getElementById("noResults");
    if (noResults) noResults.style.display = "none";

    const p = document.getElementById("purpose");
    if (p) p.value = "all";
    document.querySelectorAll('input[name="propertyType"]').forEach(cb => { cb.checked = false; });
    const loc = document.getElementById("location");
    if (loc) loc.value = "";
    const b = document.getElementById("budgetFilter");
    if (b) b.value = "any";
    const bed = document.getElementById("bedroomFilter");
    if (bed) bed.value = "any";
    const ar = document.getElementById("areaFilter");
    if (ar) ar.value = "any";
}

function resetPropertyFilters() {
    showAllProperties();
    searchProperties(false);
}

function initializePropertyFilters() {
    const budgetFilter = document.getElementById("budgetFilter");
    const purposeFilter = document.getElementById("purpose");
    if (!budgetFilter || !purposeFilter) return;

    function updateBudgetOptions() {
        const isRent = purposeFilter.value === "rent";
        const options = isRent
            ? [
                ["any", "Any budget"],
                ["under", "Under ₹25,000/mo"],
                ["middle", "₹25,000–₹50,000/mo"],
                ["upper", "₹50,000–₹1 Lakh/mo"],
                ["over", "₹1 Lakh/mo and above"]
            ]
            : [
                ["any", "Any budget"],
                ["under", "Under ₹50 Lakh"],
                ["middle", "₹50 Lakh–₹1 Cr"],
                ["upper", "₹1 Cr–₹2 Cr"],
                ["over", "₹2 Cr and above"]
            ];
        const selectedBudget = budgetFilter.value;
        budgetFilter.replaceChildren(
            ...options.map(([value, label]) => {
                const option = document.createElement("option");
                option.value = value;
                option.textContent = label;
                return option;
            })
        );
        budgetFilter.value = selectedBudget;
    }

    document.querySelectorAll('input[name="propertyType"], #budgetFilter, #bedroomFilter, #areaFilter')
        .forEach(filter => {
            filter.addEventListener("change", () => searchProperties(false));
        });

    purposeFilter.addEventListener("change", () => {
        updateBudgetOptions();
        searchProperties(false);
    });
}


// ==============================
// CONTACT & ENQUIRY
// ==============================

function contactAgent(propertyName) {
    const contactSection = document.getElementById("contact");
    const interestField = document.getElementById("propertyInterest");
    if (interestField) {
        interestField.value = propertyName;
    }
    if (contactSection) {
        contactSection.scrollIntoView({ behavior: "smooth" });
        const nameInput = document.getElementById("contactName");
        if (nameInput) nameInput.focus({ preventScroll: true });
    }
}

async function submitContact(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const name = document.getElementById("contactName").value.trim();
    const phone = document.getElementById("contactPhone").value.trim();
    const requirement = document.getElementById("contactRequirement").value;
    const propertyInterest = document.getElementById("propertyInterest")?.value.trim() || "";
    const submitButton = form.querySelector('[type="submit"]');

    setFormStatus(form, "");
    submitButton.disabled = true;

    try {
        const res = await postApi("/api/enquiries", {
            name,
            phone,
            requirement,
            propertyInterest
        });
        form.reset();
        const badge = res.classification ? ` (${res.classification})` : "";
        setFormStatus(
            form,
            `Thanks ${name}! Your enquiry has been routed to our local property advisor${badge}.`,
            "success"
        );
    } catch (error) {
        setFormStatus(form, error.message, "error");
    } finally {
        submitButton.disabled = false;
    }
}


// ==============================
// LIST PROPERTY MODAL
// ==============================

function openModal() {
    const m = document.getElementById("propertyModal");
    if (m) m.classList.add("show");
}

function closeModal() {
    const m = document.getElementById("propertyModal");
    if (m) m.classList.remove("show");
}

window.addEventListener("click", function(event) {
    const modal = document.getElementById("propertyModal");
    if (event.target === modal) closeModal();
    const favModal = document.getElementById("favoritesModal");
    if (event.target === favModal) closeFavoritesModal();
});

async function listProperty(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const submitButton = form.querySelector('[type="submit"]');
    const payload = {
        name: document.getElementById("propertyOwnerName").value.trim(),
        phone: document.getElementById("propertyOwnerPhone").value.trim(),
        purpose: document.getElementById("propertyPurpose").value,
        location: document.getElementById("propertyLocation").value.trim(),
        title: document.getElementById("propertyTitle").value.trim(),
        description: document.getElementById("propertyDescription").value.trim(),
        propertyType: document.getElementById("propertyType").value,
        bedrooms: document.getElementById("propertyBedrooms")?.value || "",
        bathrooms: document.getElementById("propertyBathrooms")?.value || "",
        areaSqFt: document.getElementById("propertyArea").value,
        expectedPrice: document.getElementById("propertyPrice").value
    };

    setFormStatus(form, "");
    submitButton.disabled = true;

    try {
        await postApi("/api/property-submissions", payload);
        form.reset();
        setFormStatus(
            form,
            "Your property details were received and saved for agent review. They will stay private until verified.",
            "success"
        );
    } catch (error) {
        setFormStatus(form, error.message, "error");
    } finally {
        submitButton.disabled = false;
    }
}


// ==============================
// API HELPERS
// ==============================

function postApi(path, payload) {
    return requestApi(path, { method: "POST", payload });
}

async function requestApi(path, { method = "GET", payload } = {}) {
    let response;
    try {
        response = await fetch(window.propertyPointApiUrl(path), {
            method,
            headers: payload ? { "Content-Type": "application/json" } : {},
            credentials: "include",
            body: payload ? JSON.stringify(payload) : undefined
        });
    } catch {
        throw new Error("Could not connect to Property Point backend. Make sure `python server.py` is running.");
    }

    let result;
    try {
        result = await response.json();
    } catch {
        throw new Error("The server returned an invalid response.");
    }

    if (!response.ok || !result.ok) {
        throw new Error(result.error?.message || "Request could not be completed.");
    }
    return result.data;
}


// ==============================
// DYNAMIC CARD RENDERING
// ==============================

async function loadApprovedListings({ gridId, statusId, variant, propertyTypes }) {
    const grid = document.getElementById(gridId);
    const status = document.getElementById(statusId);
    if (!grid) return;

    try {
        const response = await requestApi("/api/properties?limit=50&sort_by=recommended");
        const listings = response.items.filter(listing =>
            propertyTypes.includes(listing.propertyType)
        );

        if (listings.length > 0) {
            // Replace any static cards with database-backed verified records
            grid.innerHTML = "";
            const favs = getStoredFavorites();

            listings.forEach(listing => {
                grid.appendChild(createApprovedPropertyCard(listing, variant, favs));
            });

            if (variant === "residential") {
                searchProperties(false);
            } else if (variant === "commercial" && typeof filterCommercialProperties === "function") {
                filterCommercialProperties();
            } else if (variant === "land" && typeof filterLandProperties === "function") {
                filterLandProperties();
            }
        }
    } catch (error) {
        if (status) {
            status.textContent = `Approved owner listings could not be loaded: ${error.message}`;
        }
    }
}

function createApprovedPropertyCard(listing, variant, favs = []) {
    const card = document.createElement(variant === "residential" ? "div" : "article");
    const purpose = listing.purpose === "Rent" ? "rent" : "buy";
    const type = listing.propertyType === "Flat" ? "Flats" : listing.propertyType;
    const propertyImage = listing.imageUrl ||
        "https://images.unsplash.com/photo-1600607687920-4e2a09cf159d?auto=format&fit=crop&w=900&q=80";

    card.className = "property-card";
    card.dataset.id = listing.id;
    if (variant === "commercial") card.classList.add("commercial-card");
    else if (variant === "land") card.classList.add("land-card");

    card.dataset.purpose = purpose;
    card.dataset.location = (listing.location || "").toLowerCase();
    card.dataset.search = `${listing.title} ${listing.propertyType} ${listing.location}`.toLowerCase();
    if (variant === "residential") card.dataset.type = type;

    const isFav = favs.includes(listing.id);

    const imageWrapper = document.createElement("div");
    imageWrapper.className = "property-image";
    imageWrapper.innerHTML = `
        <img src="${propertyImage}" alt="${listing.title} in ${listing.location}" loading="lazy">
        <span class="tag ${purpose === 'rent' ? 'rent' : ''}">FOR ${purpose.toUpperCase()}</span>
        ${listing.avm?.badge ? `<span class="tag deal-tag ${listing.avm.dealRating === 'underpriced' ? 'great-deal' : ''}">${listing.avm.badge}</span>` : ''}
        <button class="favorite ${isFav ? 'active' : ''}" type="button" aria-label="Save ${listing.title}" onclick="favoriteProperty(this, '${listing.id}')">
            <i class="${isFav ? 'fa-solid' : 'fa-regular'} fa-heart" ${isFav ? 'style="color:#e63946"' : ''}></i>
        </button>
    `;

    const info = document.createElement("div");
    info.className = "property-info";

    const typeLabel = document.createElement("p");
    typeLabel.className = "property-type";
    typeLabel.textContent = type;

    const title = document.createElement("h3");
    const titleLink = document.createElement("a");
    titleLink.href = `property.html?id=${listing.id}`;
    titleLink.textContent = listing.title;
    titleLink.style.color = "inherit";
    titleLink.style.textDecoration = "none";
    title.appendChild(titleLink);

    const location = document.createElement("p");
    location.className = "location";
    location.innerHTML = `<i class="fa-solid fa-location-dot"></i> ${listing.location}`;

    const details = createApprovedPropertyDetails(listing);

    const bottom = document.createElement("div");
    bottom.className = "property-bottom";
    const price = document.createElement("strong");
    price.textContent = `${formatPropertyPrice(listing.expectedPrice)}${purpose === "rent" ? "/mo" : ""}`;

    const actionsDiv = document.createElement("div");
    actionsDiv.style.display = "flex";
    actionsDiv.style.gap = "8px";

    const viewBtn = document.createElement("a");
    viewBtn.href = `property.html?id=${listing.id}`;
    viewBtn.className = "view-detail-link";
    viewBtn.style.padding = "7px 12px";
    viewBtn.style.borderRadius = "6px";
    viewBtn.style.border = "1px solid var(--border)";
    viewBtn.textContent = "Details";

    const contactButton = document.createElement("button");
    contactButton.type = "button";
    contactButton.textContent = "Contact";
    contactButton.addEventListener("click", () =>
        contactAgent(`${listing.title} in ${listing.location}`)
    );

    actionsDiv.append(viewBtn, contactButton);
    bottom.append(price, actionsDiv);

    info.append(typeLabel, title, location);
    if (details.childElementCount > 0) info.appendChild(details);
    if (listing.description) {
        const desc = document.createElement("p");
        desc.className = "approved-property-description";
        desc.textContent = listing.description;
        info.appendChild(desc);
    }
    info.appendChild(bottom);

    card.append(imageWrapper, info);
    return card;
}

function createApprovedPropertyDetails(listing) {
    const details = document.createElement("div");
    details.className = "property-details";
    const features = [
        listing.bedrooms ? ["fa-bed", listing.bedrooms.replace(" BHK", " Beds")] : null,
        listing.bathrooms ? ["fa-bath", listing.bathrooms] : null,
        listing.areaSqFt ? ["fa-ruler-combined", `${Number(listing.areaSqFt).toLocaleString("en-IN")} sq.ft`] : null
    ].filter(Boolean);

    features.forEach(([iconClass, label]) => {
        const feature = document.createElement("span");
        feature.innerHTML = `<i class="fa-solid ${iconClass}"></i> ${label}`;
        details.appendChild(feature);
    });
    return details;
}

function formatPropertyPrice(price) {
    return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        maximumFractionDigits: 2
    }).format(price);
}

function setFormStatus(form, message, state = "") {
    const status = form.querySelector("[data-form-status]");
    if (status) {
        status.textContent = message;
        status.dataset.state = state;
    }
}


// ==============================
// ALGORITHM 1: HOMEPAGE AVM WIDGET
// ==============================

async function calculateHomeValuation(event) {
    event.preventDefault();
    const location = document.getElementById("valLocation").value;
    const propertyType = document.getElementById("valType").value;
    const areaSqFt = Number(document.getElementById("valArea").value) || 1000;
    const purpose = document.getElementById("valPurpose").value;
    const resultBox = document.getElementById("valuationResultBox");

    try {
        const res = await postApi("/api/analytics/valuation", {
            location,
            propertyType,
            areaSqFt,
            purpose,
            amenities: ["Lift", "Security", "Covered Parking"]
        });

        resultBox.style.display = "block";
        document.getElementById("valEstimatedDisplay").textContent = formatPropertyPrice(res.estimatedPrice);
        document.getElementById("valRangeDisplay").textContent =
            `${formatPropertyPrice(res.fairRangeMin)} – ${formatPropertyPrice(res.fairRangeMax)}`;
        document.getElementById("valRateDisplay").textContent =
            `₹${Number(res.benchmarkRatePerSqFt).toLocaleString("en-IN")} / sq.ft`;
    } catch (err) {
        alert(err.message || "Failed to calculate valuation.");
    }
}


// ==============================
// ALGORITHM 6: HOMEPAGE MORTGAGE CALCULATOR
// ==============================

function initHomeMortgageCalculator() {
    const priceSlider = document.getElementById("homeLoanPrice");
    const downSlider = document.getElementById("homeLoanDownPct");
    const tenureSlider = document.getElementById("homeLoanTenure");
    const rateInput = document.getElementById("homeLoanRate");

    if (!priceSlider || !downSlider || !tenureSlider || !rateInput) return;

    function recalculate() {
        const price = Number(priceSlider.value);
        const downPct = Number(downSlider.value);
        const tenureYears = Number(tenureSlider.value);
        const rate = Number(rateInput.value) || 8.5;

        const downAmount = price * (downPct / 100);
        document.getElementById("homeLoanPriceDisplay").textContent = formatPropertyPrice(price);
        document.getElementById("homeLoanDownDisplay").textContent = `${downPct}% (${formatPropertyPrice(downAmount)})`;
        document.getElementById("homeLoanTenureDisplay").textContent = `${tenureYears} Years`;

        const principal = price - downAmount;
        const monthlyRate = (rate / 100) / 12;
        const totalMonths = tenureYears * 12;

        let emi = 0;
        if (monthlyRate === 0) {
            emi = principal / totalMonths;
        } else {
            const comp = Math.pow(1 + monthlyRate, totalMonths);
            emi = principal * monthlyRate * (comp / (comp - 1));
        }

        const totalPayable = emi * totalMonths;
        const totalInterest = totalPayable - principal;

        document.getElementById("homeCalculatedEmi").textContent = `${formatPropertyPrice(emi)} / mo`;
        document.getElementById("homePrincipalLoan").textContent = formatPropertyPrice(principal);
        document.getElementById("homeTotalInterest").textContent = formatPropertyPrice(totalInterest);
        document.getElementById("homeTotalPayable").textContent = formatPropertyPrice(totalPayable);
    }

    priceSlider.addEventListener("input", recalculate);
    downSlider.addEventListener("input", recalculate);
    tenureSlider.addEventListener("input", recalculate);
    rateInput.addEventListener("input", recalculate);
    recalculate();
}


// ==============================
// INIT ON DOM LOAD
// ==============================

window.addEventListener("DOMContentLoaded", () => {
    initializePropertyFilters();
    updateNavFavCount();
    initHomeMortgageCalculator();

    const listingPages = [
        {
            gridId: "propertyGrid",
            statusId: "propertyFeedStatus",
            variant: "residential",
            propertyTypes: ["Flat", "Builder Floor", "Independent Villa"]
        },
        {
            gridId: "commercialGrid",
            statusId: "commercialFeedStatus",
            variant: "commercial",
            propertyTypes: ["Commercial Space"]
        },
        {
            gridId: "landGrid",
            statusId: "landFeedStatus",
            variant: "land",
            propertyTypes: ["Plot"]
        }
    ];

    const currentPage = listingPages.find(({ gridId }) => document.getElementById(gridId));
    if (currentPage) {
        loadApprovedListings(currentPage);
    }

    if (new URLSearchParams(window.location.search).get("listProperty") === "1") {
        openModal();
    }
});