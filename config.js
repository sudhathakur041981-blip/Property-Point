window.PROPERTY_POINT_API_BASE = "https://property-point.onrender.com";

window.propertyPointApiUrl = function (path) {
    const baseUrl = window.PROPERTY_POINT_API_BASE.replace(/\/+$/, "");
    return `${baseUrl}${path}`;
};
