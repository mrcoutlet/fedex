// static/js/main.js

document.addEventListener('DOMContentLoaded', () => {
    // ... (existing code for add-tracking-form, logout-btn, etc.) ...

    const trackingList = document.querySelector('.tracking-list');
    const receiptDisplay = document.getElementById('receipt-display');
    const closeReceiptBtn = document.getElementById('close-receipt-btn');
    const receiptContentPlaceholder = document.getElementById('receipt-content-placeholder');

    if (trackingList) {
        trackingList.addEventListener('click', async (event) => {
            const target = event.target;

            // Handle View Details Button
            if (target.classList.contains('view-details-btn')) {
                const trackingId = target.dataset.trackingId;
                if (trackingId) {
                    try {
                        const response = await fetch(`/get-tracking-details/${trackingId}`);
                        const data = await response.json();

                        if (response.ok && data.success) {
                            displayReceipt(data.receiptHtml); // Only pass receiptHtml
                        } else {
                            // Show the specific error message from the backend
                            alert(`Error: ${data.message || 'Failed to fetch tracking details.'}`);
                        }
                    } catch (error) {
                        console.error('Error fetching tracking details:', error);
                        alert('An unexpected error occurred while fetching tracking details.');
                    }
                }
            }
            // Handle Email Receipt Button (NEW)
            else if (target.classList.contains('email-receipt-dashboard-btn')) {
                const trackingId = target.dataset.trackingId;
                if (trackingId) {
                    const recipientEmail = prompt("Please enter the recipient's email address:");
                    if (recipientEmail) {
                        try {
                            const response = await fetch(`/email-receipt-dashboard/${trackingId}`, {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/x-www-form-urlencoded',
                                },
                                body: `recipient_email=${encodeURIComponent(recipientEmail)}`,
                            });
                            const data = await response.json();

                            if (response.ok && data.success) {
                                alert(data.message);
                            } else {
                                alert(`Error: ${data.message || 'Failed to email receipt.'}`);
                            }
                        } catch (error) {
                            console.error('Error emailing receipt:', error);
                            alert('An unexpected error occurred while emailing the receipt.');
                        }
                    } else if (recipientEmail === "") {
                        alert("Email address cannot be empty.");
                    }
                }
            }
            // Handle Print Receipt Button (NEW)
            else if (target.classList.contains('print-receipt-dashboard-btn')) {
                const trackingId = target.dataset.trackingId;
                if (trackingId) {
                    // Open the PDF in a new tab for printing/downloading
                    window.open(`/download-pdf-dashboard/${trackingId}`, '_blank');
                }
            }
        });
    }

    if (closeReceiptBtn) {
        closeReceiptBtn.addEventListener('click', () => {
            receiptDisplay.classList.add('hidden');
            receiptContentPlaceholder.innerHTML = ''; // Clear content when closing
        });
    }

    // This function will now only handle displaying HTML content
    function displayReceipt(htmlContent) {
        receiptContentPlaceholder.innerHTML = htmlContent;
        receiptDisplay.classList.remove('hidden');
    }

    // ... (rest of your existing JS) ...
});