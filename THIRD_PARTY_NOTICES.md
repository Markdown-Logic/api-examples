# Third-party notices

The examples are licensed under the repository's [MIT License](LICENSE), with the copyright notice supplied by Markdown Logic. That license does not replace the terms of external dependencies or toolchains.

## Java JSON dependency

The Java examples use **Gson 2.13.2**, published by the Gson project under the **Apache License 2.0**. The dependency is declared in `java/pom.xml`; its source and binaries are not vendored in this repository. Applications that redistribute it should retain its upstream license and notices.

- Coordinates: `com.google.code.gson:gson:2.13.2`
- Project: <https://github.com/google/gson>
- License: <https://www.apache.org/licenses/LICENSE-2.0>

## API reference

The bundled OpenAPI document is published by Markdown Logic at the URL recorded in [reference/provenance.json](reference/provenance.json). It is retained unchanged, including its upstream metadata. The upstream document does not declare a separate license in `info.license`; this repository does not add or alter that metadata.

## Runtimes and containers

The optional quick starts download official language images and operating-system packages separately. Those images, runtimes and packages are not included in the source distribution and retain their publishers' licenses. See [containers/README.md](containers/README.md) for the image names.

The report fixtures are synthetic examples. No third-party image, font, document or customer dataset is included.
