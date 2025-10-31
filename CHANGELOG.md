All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and the version number follows the community convention:
`odoo_major.odoo_minor.module_major.module_minor.module_patch`
(e.g. `18.0.1.0.0` = Odoo 18.1 + module v1.0.0), which also aligns
with [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

## [18.0.1.2.0] - 2025-10-31
### Added
- ODOO-135: Refund reason field for better transaction tracking

### Fixed
- ODOO-148: Webhook validation issues for improved reliability
- ODOO-134: Floating-point arithmetic calculation error for accurate financial calculations
- ODOO-137: Incorrect decimal precision in calculations for better accuracy
- ODOO-136: Unnecessary filter removal from code for better performance

## [18.0.1.1.0] - 2025-10-24
### Added
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
