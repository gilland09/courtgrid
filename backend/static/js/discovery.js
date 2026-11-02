document.getElementById('map').replaceChildren();
const facilityMap = L.map('map').setView([11.5583, 124.3958], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
}).addTo(facilityMap);

const activeMarkers = [];
const facilityList = document.getElementById('facility-list');
const sportsFilter = document.getElementById('sports-filter');
const filterButton = document.getElementById('filter-facilities');

function renderFacilitiesList(facilities) {
    facilityList.replaceChildren();

    if (facilities.length === 0) {
        const emptyMessage = document.createElement('p');
        emptyMessage.className = 'text-body-secondary';
        emptyMessage.textContent = 'No facilities match the selected sports.';
        facilityList.append(emptyMessage);
        return;
    }

    const row = document.createElement('div');
    row.className = 'row g-3';

    facilities.forEach((facility) => {
        const column = document.createElement('div');
        column.className = 'col-12 col-md-6 col-lg-4';

        const card = document.createElement('article');
        card.className = 'card h-100';

        const cardBody = document.createElement('div');
        cardBody.className = 'card-body d-flex flex-column';

        const title = document.createElement('h3');
        title.className = 'card-title h5';
        title.textContent = facility.name;
        cardBody.append(title);

        const barangay = document.createElement('p');
        barangay.className = 'card-text mb-1';
        barangay.textContent = `Barangay: ${facility.barangay || 'Not specified'}`;
        cardBody.append(barangay);

        const capacity = document.createElement('p');
        capacity.className = 'card-text';
        capacity.textContent = `Capacity: ${facility.capacity ?? 'Not specified'}`;
        cardBody.append(capacity);

        const sportBadges = document.createElement('div');
        sportBadges.className = 'd-flex flex-wrap gap-2 mb-3';
        (facility.supported_sports || []).forEach((sport) => {
            const badge = document.createElement('span');
            badge.className = 'badge text-bg-primary';
            badge.textContent = sport.name;
            sportBadges.append(badge);
        });
        cardBody.append(sportBadges);

        const availabilityLink = document.createElement('a');
        availabilityLink.className = 'btn btn-outline-primary mt-auto align-self-start';
        availabilityLink.href = '#';
        availabilityLink.textContent = 'View Availability';
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
        const name = document.createElement('strong');
        name.textContent = facility.name;
        popup.append(name);

        const sportsList = document.createElement('ul');
        sportsList.className = 'mb-0 mt-1 ps-3';
        (facility.supported_sports || []).forEach((sport) => {
            const item = document.createElement('li');
            item.textContent = sport.name;
            sportsList.append(item);
        });
        popup.append(sportsList);

        const marker = L.marker([latitude, longitude])
            .addTo(facilityMap)
            .bindPopup(popup);
        activeMarkers.push(marker);
    });
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
    fetchFacilities();
    sportsFilter.addEventListener('change', () => fetchFacilities(getSelectedSports()));
    filterButton.addEventListener('click', () => fetchFacilities(getSelectedSports()));
});
