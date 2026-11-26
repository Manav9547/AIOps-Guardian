-- Booking API schema and seed data.
-- Applied by the app on every startup (app/db.py), so every statement must be
-- safe to run more than once.

CREATE TABLE IF NOT EXISTS trains (
    id              SERIAL PRIMARY KEY,
    number          TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    origin          TEXT    NOT NULL,
    destination     TEXT    NOT NULL,
    departs_at      TIME    NOT NULL,           -- daily service
    arrives_at      TIME    NOT NULL,
    seats_total     INTEGER NOT NULL CHECK (seats_total > 0),
    seats_available INTEGER NOT NULL CHECK (seats_available >= 0),
    fare_cents      INTEGER NOT NULL CHECK (fare_cents >= 0),
    CHECK (seats_available <= seats_total)
);

CREATE INDEX IF NOT EXISTS trains_route_idx ON trains (origin, destination);

CREATE TABLE IF NOT EXISTS bookings (
    id          SERIAL PRIMARY KEY,
    train_id    INTEGER     NOT NULL REFERENCES trains (id),
    passenger   TEXT        NOT NULL,
    seats       INTEGER     NOT NULL CHECK (seats > 0),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
    id            SERIAL PRIMARY KEY,
    booking_id    INTEGER     NOT NULL UNIQUE REFERENCES bookings (id),
    amount_cents  INTEGER     NOT NULL CHECK (amount_cents >= 0),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed trains. ON CONFLICT keeps re-runs from duplicating rows or resetting
-- seat counts.
INSERT INTO trains (number, name, origin, destination, departs_at, arrives_at,
                    seats_total, seats_available, fare_cents) VALUES
    ('T101', 'Morning Express',   'Delhi',     'Mumbai',    '06:00', '22:00', 200, 200, 185000),
    ('T102', 'Night Mail',        'Mumbai',    'Delhi',     '21:30', '13:30', 200, 200, 175000),
    ('T201', 'Coastal Link',      'Mumbai',    'Goa',       '07:15', '15:45', 150, 150,  95000),
    ('T202', 'Coastal Link',      'Goa',       'Mumbai',    '16:30', '01:00', 150, 150,  95000),
    ('T301', 'Garden City Fast',  'Bengaluru', 'Chennai',   '06:30', '11:30', 180, 180,  70000),
    ('T302', 'Garden City Fast',  'Chennai',   'Bengaluru', '14:00', '19:00', 180, 180,  70000),
    ('T401', 'Eastern Arrow',     'Delhi',     'Kolkata',   '17:00', '10:00', 220, 220, 210000),
    ('T402', 'Eastern Arrow',     'Kolkata',   'Delhi',     '15:00', '08:00', 220, 220, 210000),
    ('T501', 'Deccan Shuttle',    'Pune',      'Mumbai',    '07:00', '10:15', 120, 120,  35000),
    ('T502', 'Deccan Shuttle',    'Mumbai',    'Pune',      '18:00', '21:15', 120, 120,  35000),
    ('T601', 'Lake City Special', 'Delhi',     'Jaipur',    '08:00', '12:30', 160, 160,  60000),
    -- One seat only: used to test that two parallel bookings of the last seat
    -- give one success and one 409 (commit 6).
    ('T999', 'Last Seat Special', 'Delhi',     'Jaipur',    '09:00', '13:30',   1,   1,  60000)
ON CONFLICT (number) DO NOTHING;
