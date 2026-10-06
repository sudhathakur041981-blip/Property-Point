window.PROPERTY_POINT_API_BASE = "";

window.propertyPointApiUrl = function (path) {
    const baseUrl = window.PROPERTY_POINT_API_BASE.replace(/\/+$/, "");
    return `${baseUrl}${path}`;
};
