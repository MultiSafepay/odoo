/** @odoo-module */

// Copyright (c) MultiSafepay, Inc. All rights reserved.
// This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.

import {describe, expect, test} from "@odoo/hoot";
import {buildCustomer} from "@pos_multisafepay_cloud/app/payment_multisafepay_cloud";

describe("buildCustomer", () => {
    test("returns null if no partner is attached to the order", () => {
        const order = {};
        expect(buildCustomer(order)).toBe(null);
        expect(buildCustomer(null)).toBe(null);
    });

    test("correctly parses and structures standard partner data", () => {
        const order = {
            partner: {
                id: 123,
                name: "Jane Doe",
                lang: "es_ES",
                street: "Gran Via 25",
                street2: "Planta 4",
                zip: "28013",
                city: "Madrid",
                state_id: {name: "Madrid"},
                country_id: {code: "ES"},
                phone: "+34600000000",
                email: "jane.doe@example.com",
            },
        };

        const customer = buildCustomer(order);

        expect(customer).toEqual({
            name: "Jane Doe",
            locale: "es_ES",
            first_name: "Jane",
            last_name: "Doe",
            address1: "Gran Via 25",
            address2: "Planta 4",
            zip_code: "28013",
            city: "Madrid",
            state: "Madrid",
            country: "ES",
            phone: "+34600000000",
            email: "jane.doe@example.com",
        });
    });

    test("fallbacks and handles missing or empty attributes", () => {
        const order = {
            getPartner: () => ({
                name: "Onlyfirstname",
                street: "Gran Via 25",
                phone: "",
                mobile: "+34611111111",
            }),
        };

        const customer = buildCustomer(order);

        expect(customer).toEqual({
            name: "Onlyfirstname",
            // Fallback locale
            locale: "en_US",
            first_name: "Onlyfirstname",
            address1: "Gran Via 25",
            // Fallback to mobile
            phone: "+34611111111",
        });

        // Make sure empty values and relations like address2, zip, email, and last_name are stripped out of the keys
        expect("address2" in customer).toBe(false);
        expect("zip_code" in customer).toBe(false);
        expect("email" in customer).toBe(false);
        expect("last_name" in customer).toBe(false);
        expect("reference" in customer).toBe(false);
    });
});
