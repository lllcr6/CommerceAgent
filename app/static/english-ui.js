/* Display persisted enum labels in English without changing form values or API payloads. */
(() => {
  const labels = {unsatisfied: 'Unsatisfied', okay: 'Okay', satisfied: 'Satisfied',
    cancelled: 'Cancelled', shipped: 'Shipped', awaiting_payment: 'Awaiting payment',
    unresolved: 'Unresolved', resolved: 'Resolved', dismissed: 'No action needed',
    refund: 'Refund', pending: 'Pending', approved: 'Approved', rejected: 'Rejected',
    after_sales: 'After-sales', complaint: 'Complaint', question: 'Question',
    handed_off: 'Human support', paid: 'Paid', completed: 'Completed', closed: 'Closed',
    delivered: 'Delivered', awaiting_confirmation: 'Awaiting confirmation',
    shipping: 'Shipping', order_status: 'Orders', product_policy: 'Products and policies',
    return_refund: 'Returns and refunds', warranty_support: 'After-sales',
    human_support: 'Human support', chitchat: 'Greetings', other: 'Other'};
  // Translate complete enum values only; never rewrite fragments of prose.
  const display=value=>{const text=String(value ?? '');return labels[text] ?? text;};
  window.petLabel = display;
  window.petMoney = (value,currency) => {
    if (value == null || !currency) return 'Price unavailable';
    return new Intl.NumberFormat('en-US',{style:'currency',currency,currencyDisplay:currency === 'USD' ? 'symbol' : 'code'}).format(value);
  };
  function update(root) {
    if (!root || root.nodeType !== Node.ELEMENT_NODE) return;
    // Never translate customer-authored conversation text, typed input, or code.
    if (root.closest('script,style,textarea,pre,code,.row.user,.message.user,.ticket-description,.ticket-result,.bubble,.message-bubble')) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement.closest('script,style,textarea,pre,code,.row.user,.message.user,.ticket-description,.ticket-result,.bubble,.message-bubble')) continue;
      const key = node.nodeValue.trim();
      const translated=display(key);
      if(translated!==key) node.nodeValue=node.nodeValue.replace(key,translated);
    }
  }
  function start() {
    update(document.body);
    new MutationObserver(records => {
      for (const record of records) {
        if (record.type === 'characterData') update(record.target.parentElement);
        else for (const node of record.addedNodes) update(node.nodeType === 3 ? node.parentElement : node);
      }
    }).observe(document.body, {subtree:true, childList:true, characterData:true});
    document.querySelectorAll('.brand,.mh-brand').forEach(el => {
      if (!el.querySelector('.pet-brand-mark,.mh-mascot,[data-cat]')) {
        const img=document.createElement('img');img.src='/static/paws.svg';img.alt='Pixel dog and cat paws';img.className='pet-brand-mark';el.prepend(img);
      }
    });
  }
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded',start) : start();
})();
