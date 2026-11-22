document.getElementById('map').replaceChildren();
const facilityMap = L.map('map').setView([11.5601, 124.3965], 15);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom',
    maxZoom: 19,
}).addTo(facilityMap);

const activeMarkers = [];
const facilityList = document.getElementById('facility-list');
const sportsFilter = document.getElementById('sports-filter');
const sportPills = Array.from(document.querySelectorAll('[data-sport-slug]'));
const allSportsButton = document.querySelector('[data-all-sports]');
const pinCount = document.getElementById('verified-pin-count');

function renderFacilitiesList(facilities) {
    facilityList.replaceChildren();

    if (facilities.length === 0) {
        const emptyMessage = document.createElement('p');
        emptyMessage.className = 'empty-state text-body-secondary';
        emptyMessage.textContent = 'No facilities match the selected sports.';
        facilityList.append(emptyMessage);
        return;
    }

    const row = document.createElement('div');
    row.className = 'row row-cols-1 row-cols-md-2 g-3';

    facilities.forEach((facility) => {
        const column = document.createElement('div');
        column.className = 'col';

        const card = document.createElement('article');
        card.className = 'facility-card h-100';

        const photoHeader = document.createElement('div');
        photoHeader.className = 'facility-card-photo';
        const placeholder = document.createElement('div');
        placeholder.className = 'facility-card-photo-placeholder';
        placeholder.textContent = 'CourtGrid venue';
        if (facility.cover_photo_url) {
            const photo = document.createElement('img');
            photo.src = facility.cover_photo_url;
            photo.alt = `${facility.name} venue`;
            photo.loading = 'lazy';
            photo.addEventListener('error', () => {
                photoHeader.replaceChildren(placeholder);
            }, { once: true });
            photoHeader.append(photo);
        } else {
            photoHeader.append(placeholder);
        }
        card.append(photoHeader);

        const cardBody = document.createElement('div');
        cardBody.className = 'card-body d-flex flex-column';

        const facilityLabel = document.createElement('span');
        facilityLabel.className = 'facility-eyebrow';
        facilityLabel.textContent = 'CourtGrid-Verified Venue';
        cardBody.append(facilityLabel);

        const title = document.createElement('h3');
        title.className = 'card-title h5 mt-2';
        title.textContent = facility.name;
        cardBody.append(title);

        const location = document.createElement('p');
        location.className = 'facility-location';
        location.textContent = facility.address || facility.barangay || 'Naval, Biliran';
        cardBody.append(location);

        const verification = document.createElement('p');
        verification.className = facility.is_verified && facility.verification_status === 'verified'
            ? 'location-status is-verified'
            : 'location-status';
        verification.textContent = facility.is_verified && facility.verification_status === 'verified'
            ? 'Verified location'
            : 'Pending platform verification';
        cardBody.append(verification);

        const venueDetails = document.createElement('div');
        venueDetails.className = 'd-flex flex-wrap gap-2 mb-3';
        const courtCount = Number(facility.court_count) || 0;
        const courtBadge = document.createElement('span');
        courtBadge.className = 'venue-detail-badge';
        courtBadge.textContent = `${courtCount} ${courtCount === 1 ? 'Court' : 'Courts'}`;
        venueDetails.append(courtBadge);
        (facility.amenities || []).slice(0, 3).forEach((amenity) => {
            const badge = document.createElement('span');
            badge.className = 'venue-detail-badge';
            badge.textContent = amenity;
            venueDetails.append(badge);
        });
        if ((facility.amenities || []).length > 3) {
            const moreBadge = document.createElement('span');
            moreBadge.className = 'venue-detail-badge';
            moreBadge.textContent = `+${facility.amenities.length - 3} more`;
            venueDetails.append(moreBadge);
        }
        cardBody.append(venueDetails);

        const sportBadges = document.createElement('div');
        sportBadges.className = 'd-flex flex-wrap gap-2 mt-auto mb-3';
        (facility.supported_sports || []).forEach((sport) => {
            const badge = document.createElement('span');
            badge.className = 'sport-badge';
            badge.textContent = sport.name;
            sportBadges.append(badge);
        });
        cardBody.append(sportBadges);

        const availabilityLink = document.createElement('a');
        availabilityLink.className = 'btn btn-primary w-100';
        availabilityLink.href = `/facilities/${facility.id}/`;
        availabilityLink.textContent = 'Check Playable Slots';
        cardBody.append(availabilityLink);

        card.append(cardBody);
        column.append(card);
        row.append(column);
    });

    facilityList.append(row);
}

function renderMapPins(facilities) {
    activeMarkers.forEach((marker) => facilityMap.removeLayer(marker));
    activeMarkers.length = 0;

    facilities.forEach((facility) => {
        const latitude = Number(facility.latitude);
        const longitude = Number(facility.longitude);
        if (
            facility.latitude === null || facility.latitude === undefined
            || facility.longitude === null || facility.longitude === undefined
            || !Number.isFinite(latitude) || !Number.isFinite(longitude)
        ) {
            return;
        }

        const popup = document.createElement('div');
        popup.className = 'map-popup';
        const name = document.createElement('strong');
        name.textContent = facility.name;
        popup.append(name);

        const address = document.createElement('p');
        address.className = 'small my-1';
        address.textContent = facility.address || facility.barangay || 'Naval, Biliran';
        popup.append(address);

        const sportsList = document.createElement('div');
        sportsList.className = 'd-flex flex-wrap gap-1 my-2';
        (facility.supported_sports || []).forEach((sport) => {
            const badge = document.createElement('span');
            badge.className = 'sport-badge';
            badge.textContent = sport.name;
            sportsList.append(badge);
        });
        popup.append(sportsList);

        const availabilityLink = document.createElement('a');
        availabilityLink.className = 'btn btn-sm btn-primary';
        availabilityLink.href = `/facilities/${facility.id}/`;
        availabilityLink.textContent = 'View & Book Slots';
        popup.append(availabilityLink);

        const marker = L.marker([latitude, longitude])
            .addTo(facilityMap)
            .bindPopup(popup);
        activeMarkers.push(marker);
    });
    pinCount.textContent = `${activeMarkers.length} verified ${activeMarkers.length === 1 ? 'pin' : 'pins'}`;
    if (activeMarkers.length === 1) {
        facilityMap.setView(activeMarkers[0].getLatLng(), Math.min(facilityMap.getZoom(), 15));
    } else if (activeMarkers.length > 1) {
        facilityMap.fitBounds(
            L.featureGroup(activeMarkers).getBounds(),
            { padding: [24, 24], maxZoom: 15 },
        );
    }
}

async function fetchFacilities(sportSlugs = []) {
    facilityList.replaceChildren();
    const loadingMessage = document.createElement('p');
    loadingMessage.className = 'text-body-secondary';
    loadingMessage.textContent = 'Loading facilities...';
    facilityList.append(loadingMessage);

    const query = new URLSearchParams();
    if (sportSlugs.length > 0) {
        query.set('sports', sportSlugs.join(','));
    }
    const queryString = query.toString();
    const endpoint = `/api/facilities/${queryString ? `?${queryString}` : ''}`;

    try {
        const response = await fetch(endpoint, {
            headers: { Accept: 'application/json' },
        });
        if (!response.ok) {
            throw new Error(`Facility request failed with status ${response.status}.`);
        }

        const payload = await response.json();
        if (!Array.isArray(payload.results)) {
            throw new Error('Facility response did not contain a results list.');
        }

        renderFacilitiesList(payload.results);
        renderMapPins(payload.results);
    } catch (error) {
        console.error('Unable to load facilities.', error);
        renderMapPins([]);
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger';
        alert.setAttribute('role', 'alert');
        alert.textContent = 'Facilities could not be loaded. Please try again later.';
        facilityList.replaceChildren(alert);
    }
}

function getSelectedSports() {
    return Array.from(sportsFilter.selectedOptions, (option) => option.value);
}

document.addEventListener('DOMContentLoaded', () => {
    const initialSports = new URLSearchParams(window.location.search).get('sports');
    if (initialSports) {
        const selectedSlugs = new Set(initialSports.split(',').map((slug) => slug.trim()).filter(Boolean));
        sportsFilter.querySelectorAll('option').forEach((option) => {
            option.selected = selectedSlugs.has(option.value);
        });
    }

    function syncSportPills() {
        const selectedSlugs = new Set(getSelectedSports());
        sportPills.forEach((pill) => {
            const isSelected = selectedSlugs.has(pill.dataset.sportSlug);
            pill.setAttribute('aria-pressed', String(isSelected));
            pill.classList.toggle('is-active', isSelected);
        });
        const allSelected = selectedSlugs.size === 0;
        allSportsButton.setAttribute('aria-pressed', String(allSelected));
        allSportsButton.classList.toggle('is-active', allSelected);
    }

    sportPills.forEach((pill) => {
        pill.addEventListener('click', () => {
            const option = Array.from(sportsFilter.options)
                .find((item) => item.value === pill.dataset.sportSlug);
            option.selected = !option.selected;
            syncSportPills();
            fetchFacilities(getSelectedSports());
        });
    });

    allSportsButton.addEventListener('click', () => {
        Array.from(sportsFilter.options).forEach((option) => {
            option.selected = false;
        });
        syncSportPills();
        fetchFacilities();
    });

    syncSportPills();
    fetchFacilities(getSelectedSports());
});
