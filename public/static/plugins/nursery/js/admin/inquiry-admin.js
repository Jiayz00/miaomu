(function(window, $)
{
    'use strict';
    if(!$ || window.__nurseryInquiryAdminBound === true)
    {
        return;
    }
    window.__nurseryInquiryAdminBound = true;

    function notify(message, type)
    {
        if(typeof Prompt === 'function')
        {
            Prompt(message, type || undefined);
        } else if(window.console && console.warn) {
            console.warn(message);
        }
    }

    $(document).on('click.nurseryInquiryAdmin', '[data-phone-reveal]', function(event)
    {
        event.preventDefault();
        var button = $(this);
        if(button.data('pending') === true)
        {
            return false;
        }
        button.data('pending', true).prop('disabled', true);
        $.ajax({
            url: typeof RequestUrlHandle === 'function' ? RequestUrlHandle(button.attr('data-url')) : button.attr('data-url'),
            type: 'post',
            dataType: 'json',
            timeout: 10000,
            data: {id: button.attr('data-id') || '', request_nonce: button.attr('data-nonce') || ''},
            success: function(response)
            {
                if(response && response.code === 0 && response.data && response.data.contact_phone)
                {
                    button.closest('dd').find('[data-phone-masked]').text(response.data.contact_phone);
                    button.remove();
                    notify('已记录查看操作', 'success');
                } else {
                    notify(response && response.msg ? response.msg : '手机号查看失败');
                }
            },
            error: function(){ notify('网络请求失败，请稍后重试'); },
            complete: function(){ button.data('pending', false).prop('disabled', false); }
        });
        return false;
    });

    $(document).on('submit.nurseryInquiryAdmin', '[data-admin-inquiry-form]', function(event)
    {
        event.preventDefault();
        var form = $(this);
        var button = form.find('button[type="submit"]');
        if(button.data('pending') === true)
        {
            return false;
        }
        if(this.checkValidity && !this.checkValidity())
        {
            this.reportValidity();
            return false;
        }
        button.data('pending', true).prop('disabled', true);
        $.ajax({
            url: typeof RequestUrlHandle === 'function' ? RequestUrlHandle(form.attr('action')) : form.attr('action'),
            type: 'post',
            dataType: 'json',
            timeout: 15000,
            data: form.serialize(),
            success: function(response)
            {
                if(response && response.code === 0)
                {
                    notify(response.msg || '操作成功', 'success');
                    window.setTimeout(function(){ window.location.reload(); }, 350);
                } else {
                    notify(response && response.msg ? response.msg : '操作失败');
                }
            },
            error: function(){ notify('网络请求失败，请稍后重试'); },
            complete: function(){ button.data('pending', false).prop('disabled', false); }
        });
        return false;
    });
})(window, window.jQuery);
