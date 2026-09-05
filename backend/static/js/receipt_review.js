/**
 * receipt_review.js
 * Alpine.js component for receipt item review and editing.
 * Extracted from receipt_review.html (Audit #20.110)
 */

function receiptReview(config) {
    const ocrDataElement = document.getElementById('ocr-data');
    const ocrData = ocrDataElement ? JSON.parse(ocrDataElement.textContent) : {};

    // Config values passed from the template
    const receiptId = Number(config.receiptId);
    const csrfToken = config.csrfToken;

    return {
        receiptId: receiptId,
        storeName: ocrData.store_name || 'Unknown Store',
        purchaseDate: ocrData.purchase_date || new Date().toISOString().split('T')[0],
        items: ocrData.items || [],
        crv_items: [],
        crvExpanded: false,
        ocrTotal: parseFloat(ocrData.total_amount) || ocrData.items?.reduce((sum, item) => sum + (parseFloat(item.final_price) || parseFloat(item.base_price) || 0), 0) || 0,
        metadataSaved: false,
        categories: [],
        allExpanded: false,

        init() {
            const categoriesElement = document.getElementById('categories-data');
            this.categories = categoriesElement ? JSON.parse(categoriesElement.textContent) : [];

            // Ensure all items is a valid array and has required fields
            let rawItems = this.items;
            if (!Array.isArray(rawItems)) {
                console.warn('Items is not an array, resetting to empty list', rawItems);
                rawItems = [];
            }

            // Format ocrTotal on load
            this.ocrTotal = parseFloat(this.ocrTotal).toFixed(2);

            // Format date for input
            if (this.purchaseDate && this.purchaseDate.length > 10) {
                this.purchaseDate = this.purchaseDate.split('T')[0];
            }

            const processedItems = [];
            const extractedCrvItems = [];

            rawItems.forEach(item => {
                let processed = {
                    ...item,
                    name: item.name || '',
                    base_price: (parseFloat(item.base_price) || 0).toFixed(2),
                    quantity: parseFloat(item.quantity) || 1,
                    discounts: item.discounts ? [...item.discounts] : [],
                    fees: item.fees ? [...item.fees] : [],
                    // final_price from OCR = what you paid. Fall back to base_price if missing.
                    final_price: parseFloat(item.final_price) || parseFloat(item.base_price) || 0,
                    weight: item.weight ? parseFloat(item.weight) : null,
                    unit_type: item.unit_type || '',
                    unit_price: null,  // always recalculate from final_price below
                    original_unit_price: item.original_unit_price || null,
                    total_discount: item.total_discount || 0,
                    is_bulk: item.is_bulk || (['lb', 'oz', 'g', 'kg', 'gal', 'l', 'ml', 'pt', 'qt', 'fl oz'].includes(item.unit_type) && (parseFloat(item.quantity) || 1) === 1),
                    fdc_match: item.fdc_match || null,
                    detailsExpanded: false
                };

                // Extract embedded CRV fees
                const nonCrvFees = [];
                processed.fees.forEach(fee => {
                    const desc = (fee.description || '').toUpperCase();
                    if (fee.type === 'crv' || desc.includes('CRV')) {
                        const feeAmount = parseFloat(fee.amount) || 0;
                        extractedCrvItems.push({
                            name: fee.description || 'CRV Fee',
                            base_price: feeAmount.toFixed(2),
                            quantity: 1,
                            discounts: [],
                            fees: [],
                            final_price: feeAmount.toFixed(2),
                            weight: null,
                            unit_type: 'each',
                            unit_price: feeAmount.toFixed(2),
                            is_bulk: false,
                            category: 'Other',
                            original_unit_price: null,
                            total_discount: 0,
                            fdc_match: null,
                            detailsExpanded: false
                        });
                        // Deduct the CRV fee from the parent item's final price so it balances out
                        processed.final_price -= feeAmount;
                    } else {
                        nonCrvFees.push(fee);
                    }
                });
                processed.fees = nonCrvFees;
                processed.final_price = processed.final_price.toFixed(2);

                const qty = processed.quantity || 1;
                const weight = processed.weight || 1;
                if (processed.is_bulk && processed.weight > 0) {
                    processed.unit_price = (processed.final_price / weight).toFixed(2);
                } else {
                    processed.unit_price = (processed.final_price / qty).toFixed(2);
                }

                processedItems.push(processed);
            });

            // Split CRV items from main list cleanly without proxy mutations
            this.crv_items = [
                ...extractedCrvItems,
                ...processedItems.filter(item => item.name && item.name.toUpperCase().includes('CRV'))
            ];
            this.items = processedItems.filter(item => !(item.name && item.name.toUpperCase().includes('CRV')));
        },

        get crvTotal() {
            return this.crv_items.reduce((sum, item) => sum + (parseFloat(item.final_price) || 0), 0);
        },

        updateCrvTotal() {
            // Getter automatically updates, this is just to trigger re-eval if needed
        },

        toggleAllExpanded() {
            this.allExpanded = !this.allExpanded;
            this.items.forEach(item => item.detailsExpanded = this.allExpanded);
            this.crv_items.forEach(item => item.detailsExpanded = this.allExpanded);
        },

        addItem() {
            this.items.push({
                name: 'New Item',
                base_price: "0.00",
                quantity: 1,
                discounts: [],
                fees: [],
                final_price: "0.00",
                weight: null,
                unit_type: 'each',
                unit_price: "0.00",
                is_bulk: false,
                detailsExpanded: true
            });
            this.$nextTick(() => {
                const container = document.getElementById('items-list-container');
                if (container) container.scrollTop = container.scrollHeight;
            });
        },

        async saveMetadata() {
            try {
                const params = new URLSearchParams();
                if (this.storeName) params.append('store_name', this.storeName);
                if (this.purchaseDate) params.append('purchase_date', this.purchaseDate);
                if (this.ocrTotal > 0) params.append('total_amount', this.ocrTotal);

                const response = await fetch(`/api/receipts/${this.receiptId}`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-CSRF-Token': csrfToken
                    },
                    body: params
                });

                if (response.ok) {
                    this.metadataSaved = true;
                    setTimeout(() => this.metadataSaved = false, 3000);
                } else {
                    alert('Error saving details');
                }
            } catch (e) {
                console.error(e);
                alert('Error connecting to server');
            }
        },

        calculateDiscounts(item) {
            return item.discounts.reduce((sum, d) => sum + (parseFloat(d.amount) || 0), 0);
        },

        calculateFees(item) {
            return item.fees.reduce((sum, f) => sum + (parseFloat(f.amount) || 0), 0);
        },

        onQtyChange(item) {
            const qty = parseFloat(item.quantity) || 0;
            const weight = parseFloat(item.weight) || 1;
            const unitPrice = parseFloat(item.unit_price) || 0;

            if (item.is_bulk) {
                item.final_price = (unitPrice * weight).toFixed(2);
            } else {
                item.final_price = (unitPrice * qty).toFixed(2);
            }
            this.updateBasePrice(item);
        },

        onTotalChange(item) {
            const finalPrice = parseFloat(item.final_price) || 0;
            const qty = parseFloat(item.quantity) || 1;
            const weight = parseFloat(item.weight) || 1;

            // Derive unit_price from the final_price the user is entering
            if (item.is_bulk && weight > 0) {
                item.unit_price = (finalPrice / weight).toFixed(2);
            } else if (qty > 0) {
                item.unit_price = (finalPrice / qty).toFixed(2);
            }

            // Derive base_price = final_price + discounts - fees
            const discountTotal = this.calculateDiscounts(item);
            const feeTotal = this.calculateFees(item);
            item.base_price = (finalPrice + discountTotal - feeTotal).toFixed(2);
        },

        onUnitChange(item) {
            // This is triggered by the 'Price Per Unit' input
            const unitPrice = parseFloat(item.unit_price) || 0;
            const qty = parseFloat(item.quantity) || 0;
            const weight = parseFloat(item.weight) || 1;

            if (item.is_bulk) {
                item.final_price = (unitPrice * weight).toFixed(2);
            } else {
                item.final_price = (unitPrice * qty).toFixed(2);
            }
            this.updateBasePrice(item);
        },

        onUnitDropdownChange(item) {
            if (['lb', 'oz', 'g', 'kg', 'gal', 'l', 'ml', 'pt', 'qt', 'fl oz'].includes(item.unit_type) && item.quantity === 1) {
                item.is_bulk = true;
            } else if (item.unit_type === 'each' || !item.unit_type) {
                item.is_bulk = false;
            }
            // Recalculate based on current final price to keep total consistent
            this.onTotalChange(item);
        },

        togglePricingMode(item) {
            item.is_bulk = !item.is_bulk;
            // Recalculate based on current final price to keep total consistent
            this.onTotalChange(item);
        },

        onWeightChange(item) {
            if (item.is_bulk) {
                this.onUnitPriceChange(item); // Re-calc total based on new weight
            }
        },

        onUnitPriceChange(item) {
            this.onUnitChange(item);
        },

        updateBasePrice(item) {
            const finalPrice = parseFloat(item.final_price) || 0;
            const discounts = this.calculateDiscounts(item);
            const fees = this.calculateFees(item);
            item.base_price = (finalPrice + discounts - fees).toFixed(2);
        },

        fmt2(item, field) {
            const val = parseFloat(item[field]);
            if (!isNaN(val)) item[field] = val.toFixed(2);
        },

        async saveItems() {
            const allItemsToSave = [...this.items, ...this.crv_items];

            if (allItemsToSave.length === 0) {
                alert('No items to save!');
                return;
            }

            const sanitizedItems = allItemsToSave.map(item => ({
                ...item,
                base_price: item.base_price === '' ? 0 : Number(item.base_price),
                quantity: item.quantity === '' ? 1 : Number(item.quantity),
                unit_price: item.unit_price === '' ? null : Number(item.unit_price),
                final_price: item.final_price === '' ? 0 : Number(item.final_price),
                weight: item.weight === '' ? null : Number(item.weight),
                original_unit_price: item.original_unit_price || null,
                total_discount: item.total_discount || 0
            }));

            for (let item of sanitizedItems) {
                if (!item.name || item.name.trim() === '') {
                    alert('All items must have a name');
                    return;
                }

            }

            try {
                window.dispatchEvent(new CustomEvent('process-start', { detail: { message: 'Saving Items...' } }));
                const response = await fetch(`/api/receipts/${this.receiptId}/save-reviewed-items`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': csrfToken
                    },
                    body: JSON.stringify({
                        items: sanitizedItems,
                        purchase_date: this.purchaseDate,
                        store_name: this.storeName,
                        total_amount: this.ocrTotal > 0 ? this.ocrTotal : null
                    })
                });

                const data = await response.json();
                if (data.success) {
                    window.dispatchEvent(new CustomEvent('process-start', {
                        detail: { message: `Successfully saved ${data.items_saved} items!` }
                    }));
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    window.location.href = '/receipts';
                } else {
                    alert('Error saving items: ' + (data.message || 'Unknown error'));
                }
            } catch (error) {
                console.error('Save error:', error);
                alert('Error saving items. Please try again.');
            } finally {
                window.dispatchEvent(new CustomEvent('process-end'));
            }
        },

        async deleteReceipt() {
            if (!confirm('Are you sure you want to delete this receipt?')) return;
            try {
                const response = await fetch(`/api/receipts/${this.receiptId}`, {
                    method: 'DELETE',
                    headers: { 'X-CSRF-Token': csrfToken }
                });
                if (response.ok) {
                    window.location.href = '/receipts';
                } else {
                    alert('Error deleting receipt');
                }
            } catch (error) {
                console.error('Delete error:', error);
                alert('Error deleting receipt');
            }
        }
    };
}
