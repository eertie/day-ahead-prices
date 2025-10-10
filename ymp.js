// Verbeterde groepering: combineer slots met kleine tussenpozen
function groupConsecutiveSlots(slots, maxGapMinutes = 30) {
    if (!slots || slots.length === 0) return [];

    const groups = [];
    let currentGroup = {
        start: slots[0].hour_local,
        end: slots[0].hour_local,
        slots: [slots[0]],
        positions: [slots[0].position]
    };

    for (let i = 1; i < slots.length; i++) {
        const prev = slots[i - 1];
        const curr = slots[i];

        // Bereken het verschil in posities (elke positie = 15 minuten)
        const positionGap = curr.position - prev.position;
        const minutesGap = positionGap * 15;

        // Voeg toe aan groep als het verschil <= maxGapMinutes
        if (minutesGap <= maxGapMinutes / 15) {
            currentGroup.end = curr.hour_local;
            currentGroup.slots.push(curr);
            currentGroup.positions.push(curr.position);
        } else {
            // Start nieuwe groep
            groups.push(currentGroup);
            currentGroup = {
                start: curr.hour_local,
                end: curr.hour_local,
                slots: [curr],
                positions: [curr.position]
            };
        }
    }

    groups.push(currentGroup);
    return groups;
}

// Verbeterde tijd formatting
function formatTimeRange(start, end) {
    const startTime = start.split(' ')[1].substring(0, 5);
    const endTimeRaw = end.split(' ')[1];
    const [hours, minutes] = endTimeRaw.split(':').map(Number);

    // Voeg 15 minuten toe aan eindtijd
    const endMinutes = minutes + 15;
    const endHours = endMinutes >= 60 ? (hours + 1) % 24 : hours;
    const finalMinutes = endMinutes >= 60 ? endMinutes - 60 : endMinutes;
    const endTime = `${String(endHours).padStart(2, '0')}:${String(finalMinutes).padStart(2, '0')}`;

    return `${startTime} - ${endTime}`;
}

// Bereken totale duur inclusief gaps
function calculateTotalDuration(positions) {
    if (positions.length === 0) return 0;
    const minPos = Math.min(...positions);
    const maxPos = Math.max(...positions);
    return (maxPos - minPos + 1) * 15;
}

// Transform de data
const groupedSlots = groupConsecutiveSlots($input.item.json.cheapest_slots, 30);

return {
    json: {
        date: $input.item.json.date,
        average_ct_per_kwh: $input.item.json.average_ct_per_kwh,
        time_blocks: groupedSlots.map((group, index) => {
            const avgPrice = group.slots.reduce((sum, s) => sum + s.ct_per_kwh, 0) / group.slots.length;
            const minPrice = Math.min(...group.slots.map(s => s.ct_per_kwh));
            const maxPrice = Math.max(...group.slots.map(s => s.ct_per_kwh));

            return {
                rank: index + 1,
                time_range: formatTimeRange(group.start, group.end),
                duration_minutes: calculateTotalDuration(group.positions),
                actual_slot_count: group.slots.length,
                avg_price: parseFloat(avgPrice.toFixed(3)),
                min_price: parseFloat(minPrice.toFixed(3)),
                max_price: parseFloat(maxPrice.toFixed(3)),
                is_best: avgPrice < $input.item.json.average_ct_per_kwh * 0.8
            };
        })
    }
};






// Group consecutive time slots into blocks
function groupConsecutiveSlots(slots) {
    if (!slots || slots.length === 0) return [];

    const groups = [];
    let currentGroup = {
        start: slots[0].hour_local,
        end: slots[0].hour_local,
        avg_price: slots[0].ct_per_kwh,
        slots: [slots[0]]
    };

    for (let i = 1; i < slots.length; i++) {
        const prev = slots[i - 1];
        const curr = slots[i];

        // Check if positions are consecutive (difference of 1)
        if (curr.position - prev.position === 1) {
            // Add to current group
            currentGroup.end = curr.hour_local;
            currentGroup.slots.push(curr);
            currentGroup.avg_price = currentGroup.slots.reduce((sum, s) => sum + s.ct_per_kwh, 0) / currentGroup.slots.length;
        } else {
            // Start new group
            groups.push(currentGroup);
            currentGroup = {
                start: curr.hour_local,
                end: curr.hour_local,
                avg_price: curr.ct_per_kwh,
                slots: [curr]
            };
        }
    }

    groups.push(currentGroup);
    return groups;
}

// Format time range
function formatTimeRange(start, end) {
    const startTime = start.split(' ')[1].substring(0, 5);
    const endTimeRaw = end.split(' ')[1];
    const [hours, minutes] = endTimeRaw.split(':').map(Number);

    // Add 15 minutes to end time
    const endMinutes = minutes + 15;
    const endHours = endMinutes >= 60 ? (hours + 1) % 24 : hours;
    const finalMinutes = endMinutes >= 60 ? endMinutes - 60 : endMinutes;
    const endTime = `${String(endHours).padStart(2, '0')}:${String(finalMinutes).padStart(2, '0')}`;

    if (startTime === endTime) {
        return startTime;
    }

    return `${startTime} - ${endTime}`;
}

// Use it
const groupedSlots = groupConsecutiveSlots($input.item.json.cheapest_slots);

return {
    json: {
        date: $input.item.json.date,
        average_ct_per_kwh: $input.item.json.average_ct_per_kwh,
        time_blocks: groupedSlots.map((group, index) => ({
            rank: index + 1,
            time_range: formatTimeRange(group.start, group.end),
            duration_minutes: group.slots.length * 15,
            avg_price: parseFloat(group.avg_price.toFixed(3)),
            min_price: Math.min(...group.slots.map(s => s.ct_per_kwh)),
            max_price: Math.max(...group.slots.map(s => s.ct_per_kwh))
        }))
    }
};