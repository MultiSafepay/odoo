All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and the version number follows the community convention:
`odoo_major.odoo_minor.module_major.module_minor.module_patch`
(e.g. `18.0.1.0.0` = Odoo 18.1 + module v1.0.0), which also aligns
with [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

## [19.0.2.4.0] - 2026-07-24
### Added
- ODOO-261: Add optional shopping cart and restrict BNPL payment methods to this new setting field

### Changed
- ODOO-260: Upgrade Python SDK dependency

### Fixed
- ODOO-268: Fix multiple tax rates in a single order

## [19.0.2.3.0] - 2026-07-14
### Added
- ODOO-247: Add Validate Shopping Cart setting field

### Fixed
- ODOO-252: Fix missing 1 required positional argument: 'state_message' on set_error()

## [19.0.2.2.3] - 2026-06-17
### Fixed
- ODOO-235: Fix plugin version within the MultiSafepay order request and release of 19.0.2.2.3

## [19.0.2.2.2] - 2026-06-17
### Fixed
- ODOO-231: Fix t-if clause avoiding incorrect nested if statements

## [19.0.2.2.1] - 2026-06-17
### Fixed
- ODOO-228: Fix multi-website: payment options URLs always use global web.base.url instead of per-website domain

## [19.0.2.2.0] - 2026-04-21
### Added
- ODOO-145: Add Apple Pay visibility handling

### Fixed
- ODOO-185: Support partial payment links and minor units

## [19.0.2.1.1] - 2026-03-12
### Fixed
- ODOO-200: Fix shopping cart unit prices when taxes are configured as "Price Included"

## [19.0.2.1.0] - 2026-03-10
### Changed
- ODOO-187: Use RequestsTransport with custom session

## [19.0.2.0.0] - 2026-02-18
### Changed
- ODOO-159: Refactor module structure by separating core and enhanced features, reducing dependencies

## [19.0.1.2.1] - 2026-01-22
### Added
- ODOO-173: Add error-level logging for failed MultiSafepay order requests

## [19.0.1.2.0] - 2025-12-01
### Added
- ODOO-122: Add pricelist filter to payment method list

### Changed
- ODOO-155: Refactor cleanup logic preserving user configuration

### Fixed
- ODOO-162: Fix installation instructions in README.md file

## [19.0.1.1.0] - 2025-10-31
### Added
- ODOO-123: Refund reason field for better transaction tracking

### Fixed
- ODOO-147: Webhook validation issues for improved reliability
- ODOO-131: Floating-point arithmetic calculation error for accurate financial calculations
- ODOO-147: Precise calculation implementation in all cases to ensure accuracy
- ODOO-132: Unnecessary filter removal from code for better performance

## [19.0.1.0.0] - 2025-10-24
### Added
- Add support for Odoo 19.0.
- HTTP GET method support in webhook endpoint for improved integration flexibility
- Enhanced logging functionality across multiple modules for better debugging and monitoring

### Changed
- Enabled cart validation in Order Request for better transaction integrity

### Fixed
- Resolved duplicated merchant item ID issue in buy_x_get_y promotions
- Corrected unclear transaction status mapping for better transaction tracking
- Fixed inconsistencies in provider configuration management

## [18.0.1.0.0] - 2025-09-15
### Added
- Compatibility with Odoo 18.0.
- Support for MultiSafepay payment methods.
- Support for partial and full refunds.
- Ability to mark MultiSafepay transactions as shipped when items are delivered.
