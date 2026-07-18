(function(window, $)
{
    'use strict';

    if(!$ || window.__nurseryInquiryBound === true)
    {
        return;
    }
    window.__nurseryInquiryBound = true;

    function feedback(message, success)
    {
        var node = $('[data-inquiry-feedback]');
        if(!node.length)
        {
            return;
        }
        node.text(message || '').toggleClass('is-success', success === true);
    }

    function notify(message, type)
    {
        if(typeof Prompt === 'function')
        {
            Prompt(message, type || undefined);
        } else {
            feedback(message, type === 'success');
        }
    }

    function loginRequired()
    {
        if(typeof ModalLoad === 'function')
        {
            ModalLoad(window.__modal_login_url__ || '', '', 'common-login-modal');
        }
    }

    $(document).on('submit.nurseryInquiry', '[data-inquiry-form]', function(event)
    {
        event.preventDefault();
        var form = $(this);
        var submit = form.find('[data-inquiry-submit]');
        if(submit.data('pending') === true)
        {
            return false;
        }
        if(this.checkValidity && !this.checkValidity())
        {
            this.reportValidity();
            return false;
        }
        var url = form.attr('action');
        if(!url)
        {
            notify('询价服务暂不可用');
            return false;
        }
        submit.data('pending', true).prop('disabled', true).addClass('is-loading');
        feedback('正在核验商品和需求信息...', false);
        if($.AMUI && $.AMUI.progress)
        {
            $.AMUI.progress.start();
        }
        $.ajax({
            url: typeof RequestUrlHandle === 'function' ? RequestUrlHandle(url) : url,
            type: 'post',
            dataType: 'json',
            timeout: 15000,
            data: form.serialize(),
            success: function(response)
            {
                if(response && response.code === 0)
                {
                    feedback(response.msg || '询价提交成功', true);
                    notify(response.msg || '询价提交成功', 'success');
                    var detailUrl = response.data && response.data.detail_url ? response.data.detail_url : '';
                    if(detailUrl)
                    {
                        window.setTimeout(function(){ window.location.href = detailUrl; }, 700);
                    }
                    return;
                }
                if(response && parseInt(response.code, 10) === -400)
                {
                    loginRequired();
                }
                var message = response && response.msg ? response.msg : '询价提交失败，请检查填写内容';
                feedback(message, false);
                notify(message);
            },
            error: function()
            {
                feedback('网络请求失败，请稍后重试', false);
                notify('网络请求失败，请稍后重试');
            },
            complete: function()
            {
                if($.AMUI && $.AMUI.progress)
                {
                    $.AMUI.progress.done();
                }
                submit.data('pending', false).prop('disabled', false).removeClass('is-loading');
            }
        });
        return false;
    });

    function filterRegions(form, childName, parentId)
    {
        var child = form.find('[name="' + childName + '"]');
        if(!child.length)
        {
            return;
        }
        child.val('');
        child.find('option[data-parent]').each(function()
        {
            var option = $(this);
            option.prop('hidden', String(option.attr('data-parent')) !== String(parentId || ''));
        });
    }

    $(document).on('change.nurseryInquiry', '[data-inquiry-form] [name="region_province_id"]', function()
    {
        var form = $(this).closest('[data-inquiry-form]');
        filterRegions(form, 'region_city_id', $(this).val());
        filterRegions(form, 'region_county_id', '');
    });

    $(document).on('change.nurseryInquiry', '[data-inquiry-form] [name="region_city_id"]', function()
    {
        filterRegions($(this).closest('[data-inquiry-form]'), 'region_county_id', $(this).val());
    });

    $('[data-inquiry-form]').each(function()
    {
        var form = $(this);
        filterRegions(form, 'region_city_id', form.find('[name="region_province_id"]').val());
        filterRegions(form, 'region_county_id', form.find('[name="region_city_id"]').val());
    });
})(window, window.jQuery);
