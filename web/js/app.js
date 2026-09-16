window.onPcState = (online) => {
    console.log("PC State:", online);
};

window.onData = (payload) => {
    console.log("Data received:", payload);
};

const clockEl = document.getElementById('clock');
const dateEl = document.getElementById('date');

function updateClock() {
    const now = new Date();

    // Format time: HH:mm:ss
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    clockEl.textContent = `${hours}:${minutes}:${seconds}`;

    // Format date: Day Month Date, Year
    const options = {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    };
    dateEl.textContent = now.toLocaleDateString(undefined, options);
}

// Initial call
updateClock();
// Update every second
setInterval(updateClock, 1000);
