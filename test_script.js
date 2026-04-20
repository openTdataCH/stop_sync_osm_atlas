const { JSDOM } = require("jsdom");
const dom = new JSDOM(`<div class="map-direction-filter-container">
  <!-- Filter chip will be rendered here by JS -->
</div>`);
console.log(dom.window.document.querySelector('.map-direction-filter-container').hasChildNodes());
